"""Real SQL/Milvus restore races on a new development-only copied-page fixture.

The source Lecture 2 PDF and already parsed pages are read, not modified. This
does not re-run PDF parsing and never supplies model-quality or human labels.
Controlled scheduling forces both archive/restore lock orders. One explicitly
injected post-vector-write error tests publication/retry without stopping Milvus.
"""
import argparse
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
WORK = REPO.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def run(source_report, output):
    report = {
        "schema": "citepath-concurrent-document-storage-smoke-v1",
        "started_at": now(), "status": "running", "database_real": True,
        "milvus_real": True, "model_invoked": False, "formal_evaluation_run": False,
        "official_accepted": None, "controlled_scheduling": True,
        "fault_injected": True, "injection_kind": "local_post_vector_write_error_not_service_outage",
        "source_pdf_reparsed": False, "source_parsed_development_pages_copied": True,
        "shared_collection_deletion_guard": True, "existing_data_deleted": False,
        "data_retained": True, "checks": [], "resources": {},
        "limits": [
            "Concurrent workers use independent SQL connections and real Milvus operations within one Python process.",
            "Two lock-order schedules are deliberately gated; they are not timing-frequency measurements.",
            "The injected post-write error is not a real network/provider/Milvus failure.",
            "No Docker restart, new PDF parse, chat-model grading, independent human judgment or formal evaluation is performed.",
        ],
    }
    stage = "local_configuration"

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)

    def passed(name, **details):
        report["checks"].append({"name": name, "passed": True, **details})
        save()
        print(json.dumps({"check": name, "passed": True}), flush=True)

    vector_client_factory = None
    try:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env", override=False)
        if os.environ.get("MYSQL_HOST", "127.0.0.1") not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Local SQL host required")
        if os.environ.get("MYSQL_DATABASE", "citepath_agent") != "citepath_agent":
            raise ValueError("Project SQL database required")
        uri = urlsplit(os.environ.get("MILVUS_URI", "http://127.0.0.1:19530"))
        if (uri.hostname not in {"127.0.0.1", "localhost", "::1"} or uri.scheme not in {"http", "https"}
                or uri.username or uri.password or uri.query or uri.fragment):
            raise ValueError("Local Milvus without embedded credentials required")
        from db import auth, courses, plans, uploads
        from db.connection import connect
        from db.document_files import original_pdf_path
        from vector import segments

        def query(sql, parameters=()):
            connection = connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    return list(cursor.fetchall())
            finally:
                connection.close()

        # The application can rebuild an incompatible collection by dropping it.
        # This test must never do that to a shared collection, even on failure.
        vector_client_factory = segments._client
        class GuardedClient:
            def __init__(self):
                self.client = vector_client_factory()

            def __getattr__(self, name):
                if name in {"drop_collection", "drop_database", "create_collection"}:
                    raise RuntimeError("Shared collection mutation guard")
                return getattr(self.client, name)

        stage = "existing_hybrid_collection_preflight"
        vector_client = GuardedClient()
        if not vector_client.has_collection(segments.COLLECTION) or not segments._hybrid_ready(vector_client):
            raise RuntimeError("Existing hybrid collection required; test will not rebuild it")
        segments._client = GuardedClient

        stage = "source_binding"
        source = json.loads(source_report.read_text(encoding="utf-8-sig"))
        assert source["status"] == "passed" and source["formal_evaluation_run"] is False
        resources = source["resources"]
        source_uid = int(resources["user_id"])
        source_cid = int(resources["course_id"])
        source_document = int(resources["lecture_2_document_id"])
        source_rows = query(
            "SELECT d.id, d.course_id, d.filename, d.content_hash, d.ingest_status, d.is_active, "
            "u.username FROM documents d JOIN courses c ON c.id=d.course_id "
            "JOIN users u ON u.id=c.user_id WHERE d.id=%s AND c.id=%s AND u.id=%s",
            (source_document, source_cid, source_uid),
        )
        assert len(source_rows) == 1
        source_row = source_rows[0]
        assert source_row["username"].startswith("citepath_it_")
        assert source_row["ingest_status"] == "complete"
        pdf = (REPO / "data/mit-6.006-spring-2020/lecture-02.pdf").read_bytes()
        pdf_sha = hashlib.sha256(pdf).hexdigest()
        assert source_row["content_hash"] == pdf_sha
        source_file = original_pdf_path(source_document)
        assert source_file is not None and source_file.read_bytes() == pdf
        pages = query("SELECT page_number, body, usable FROM pages WHERE document_id=%s ORDER BY page_number", (source_document,))
        assert len(pages) == 5 and sum(bool(page["usable"]) for page in pages) == 4
        source_snapshot = digest({"row": source_row, "pages": pages})
        report["resources"].update(source_document_id=source_document, source_course_id=source_cid,
                                    original_pdf_sha256=pdf_sha, copied_page_count=len(pages))
        passed("bound_original_development_pdf_and_previously_parsed_pages")

        stage = "dedicated_fixture_creation"
        uploads.ensure_document_numbers()
        user = auth.register_user("citepath_it_r_" + secrets.token_hex(7), secrets.token_urlsafe(28))
        uid = int(user["id"])
        course = courses.create_course(uid, "Concurrent restore development fixture", "Copied Lecture 2 parsed pages; no model-quality evidence")
        cid = int(course["id"])
        report["resources"].update(user_id=uid, course_id=cid)
        saved = uploads.save_document(cid, "lecture-02-copy-concurrency.pdf", pages, pdf_sha, pdf_data=pdf)
        identifier = int(saved["document_id"])
        report["resources"]["document_id"] = identifier
        expected_count = int(saved["milvus_segments"])
        assert expected_count > 0

        def state():
            rows = query("SELECT id,course_id,content_hash,is_active,position,ingest_status FROM documents WHERE id=%s AND course_id=%s", (identifier, cid))
            assert len(rows) == 1
            return rows[0]

        def vector_rows():
            return vector_client.query(collection_name=segments.COLLECTION,
                filter=f"document_id == {identifier}",
                output_fields=["document_id", "page_number", "chunk_index", "chapter", "text"],
                limit=10000, consistency_level="Strong", timeout=15)

        def signatures(rows):
            return sorted((int(row["page_number"]), int(row["chunk_index"]), row["chapter"],
                           hashlib.sha256(row["text"].encode()).hexdigest()) for row in rows)

        initial_vectors = vector_rows()
        baseline = signatures(initial_vectors)
        assert len(baseline) == expected_count and len(set(baseline)) == expected_count

        def consistent(active):
            row = state()
            rows = vector_rows()
            assert bool(row["is_active"]) is active
            assert row["id"] == identifier and row["content_hash"] == pdf_sha
            if active:
                assert row["ingest_status"] == "complete" and row["position"] == 1
                assert signatures(rows) == baseline and len(rows) == len(set(signatures(rows)))
                assert len(plans.load_usable_pages(cid)) == 4
            else:
                assert row["position"] is None and not rows
                assert plans.load_usable_pages(cid) == []
            return len(rows)

        consistent(True)
        passed("dedicated_copied_page_fixture_indexed", vector_rows=expected_count)

        stage = "simultaneous_restores"
        courses.delete_document_rows(identifier)
        consistent(False)
        start = threading.Barrier(2)
        def restore_at_barrier():
            start.wait(timeout=10)
            return uploads.restore_document(uid, cid, identifier)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(restore_at_barrier) for _ in range(2)]
            results = [future.result(timeout=180) for future in futures]
        assert all(int(row["document_id"]) == identifier for row in results)
        consistent(True)
        assert query("SELECT COUNT(*) AS n FROM documents WHERE course_id=%s AND content_hash=%s", (cid, pdf_sha))[0]["n"] == 1
        passed("concurrent_restores_keep_one_id_and_exact_nonduplicated_vector_chunks", contenders=2)

        def gated_race(first_name):
            inside, release, contender = threading.Event(), threading.Event(), threading.Event()
            owner = uploads if first_name == "restore" else courses
            attribute = "_index_document" if first_name == "restore" else "_archive_document"
            original = getattr(owner, attribute)
            def gated(*args, **kwargs):
                assert int(args[0]) == identifier
                inside.set()
                if not release.wait(timeout=10):
                    raise RuntimeError("Controlled scheduling timed out")
                return original(*args, **kwargs)
            first = (lambda: uploads.restore_document(uid, cid, identifier)) if first_name == "restore" else (lambda: courses.delete_document_rows(identifier))
            second = (lambda: courses.delete_document_rows(identifier)) if first_name == "restore" else (lambda: uploads.restore_document(uid, cid, identifier))
            def second_started():
                contender.set()
                return second()
            setattr(owner, attribute, gated)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first_future = pool.submit(first)
                    try:
                        assert inside.wait(timeout=10)
                        second_future = pool.submit(second_started)
                        assert contender.wait(timeout=10)
                        time.sleep(.25)
                        assert not second_future.done(), "Contending operation did not wait for the document lock"
                    finally:
                        release.set()
                    first_future.result(timeout=180)
                    second_future.result(timeout=180)
            finally:
                setattr(owner, attribute, original)

        stage = "restore_then_archive"
        gated_race("restore")
        consistent(False)
        passed("archive_waits_for_inflight_restore_and_final_state_is_archived_without_vectors")

        stage = "archive_then_restore"
        uploads.restore_document(uid, cid, identifier)
        consistent(True)
        gated_race("archive")
        consistent(True)
        passed("restore_waits_for_inflight_archive_and_final_state_is_ready_with_exact_vectors")

        stage = "injected_post_write_fault"
        courses.delete_document_rows(identifier)
        consistent(False)
        original_sync = uploads.sync_pages
        injected_calls = 0
        def write_then_fault(document_id, page_rows):
            nonlocal injected_calls
            assert int(document_id) == identifier
            injected_calls += 1
            assert injected_calls == 1
            original_sync(document_id, page_rows)
            raise TimeoutError("Controlled local fault after vector write")
        uploads.sync_pages = write_then_fault
        failed = False
        try:
            uploads.restore_document(uid, cid, identifier)
        except RuntimeError:
            failed = True
        finally:
            uploads.sync_pages = original_sync
        assert failed and injected_calls == 1
        row = state()
        assert row["is_active"] == 0 and row["position"] is None and row["ingest_status"] == "failed"
        assert signatures(vector_rows()) == baseline
        passed("controlled_post_write_failure_does_not_publish_active_or_complete", injection="after_actual_vector_write")
        assert courses.get_course(uid, cid)["documents"] == [] and plans.load_usable_pages(cid) == []
        passed("inactive_failed_source_excluded_from_course_and_new_planning_despite_written_vectors")

        stage = "real_retry"
        retried = uploads.restore_document(uid, cid, identifier)
        assert int(retried["document_id"]) == identifier
        consistent(True)
        passed("retry_after_controlled_failure_releases_lock_and_rebuilds_exact_chunks")

        stage = "retained_identity_and_source_unchanged"
        own_pages = query("SELECT page_number, body, usable FROM pages WHERE document_id=%s ORDER BY page_number", (identifier,))
        assert own_pages == pages
        assert original_pdf_path(identifier).read_bytes() == pdf
        passed("fixture_original_pdf_pages_and_document_identity_retained")
        after_source = query(
            "SELECT d.id, d.course_id, d.filename, d.content_hash, d.ingest_status, d.is_active, "
            "u.username FROM documents d JOIN courses c ON c.id=d.course_id "
            "JOIN users u ON u.id=c.user_id WHERE d.id=%s AND c.id=%s AND u.id=%s",
            (source_document, source_cid, source_uid),
        )[0]
        after_pages = query("SELECT page_number, body, usable FROM pages WHERE document_id=%s ORDER BY page_number", (source_document,))
        assert digest({"row": after_source, "pages": after_pages}) == source_snapshot
        assert original_pdf_path(source_document).read_bytes() == pdf
        passed("source_course_document_pages_and_pdf_not_modified")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", failure={"stage": stage, "type": type(error).__name__})
    finally:
        if vector_client_factory is not None:
            from vector import segments
            segments._client = vector_client_factory
        report["finished_at"] = now()
        save()
    print(json.dumps({"status": report["status"], "checks_passed": len(report["checks"]),
                      "output": str(output), "failure": report.get("failure")}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Create a dedicated fixture and perform real controlled restore races")
    parser.add_argument("--source-report", type=Path, default=BACKEND / "logs/storage-http.json")
    parser.add_argument("--output", type=Path, default=BACKEND / "logs/concurrent-restore.json")
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({"status": "not_run", "database_mutated": False, "explicit_run_flag_required": True}))
        raise SystemExit(2)
    output = args.output.resolve()
    if WORK.parent.resolve() not in output.parents or REPO / "evaluation_assets" in output.parents:
        raise ValueError("Use a workspace output outside protected evaluation assets")
    if output.exists():
        raise FileExistsError("Use a new output file to retain prior observations")
    raise SystemExit(run(args.source_report.resolve(), output))
