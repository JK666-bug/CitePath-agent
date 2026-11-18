"""Build a replacement Milvus collection without changing or deleting the source.

From backend: python tools/rebuild_vector_index.py --target lecture_segments_v2
Add --apply to build. Set MILVUS_COLLECTION to the validated target separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def material_snapshot(connection) -> dict:
    """A read-only snapshot; source changes are checked again before approval."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, course_id, content_hash, kind, parent_id FROM documents "
            "WHERE is_active = 1 AND ingest_status = 'complete' ORDER BY id"
        )
        documents = list(cursor.fetchall())
        cursor.execute(
            "SELECT p.document_id, p.page_number, p.body, p.usable FROM pages p "
            "JOIN documents d ON d.id = p.document_id "
            "WHERE d.is_active = 1 AND d.ingest_status = 'complete' ORDER BY p.document_id, p.page_number"
        )
        pages = list(cursor.fetchall())
    # Finish the read transaction so the final snapshot sees concurrent changes.
    connection.rollback()
    payload = {"documents": documents, "pages": pages}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return {**payload, "fingerprint": fingerprint}


def rebuild(target: str, *, apply: bool = False, connection=None, client=None) -> dict:
    from db.connection import connect
    from vector import segments

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", target):
        raise ValueError("Use a valid, new Milvus collection name")
    source = segments.COLLECTION
    if target == source:
        raise ValueError("The replacement must differ from the active collection")
    own_connection = connection is None
    connection = connection or connect()
    client = client or segments._client()
    try:
        if client.has_collection(target):
            raise ValueError("Target collection already exists; choose a new name. No collection was deleted.")
        snapshot = material_snapshot(connection)
        result = {"source_collection": source, "target_collection": target,
                  "material_fingerprint": snapshot["fingerprint"], "document_count": len(snapshot["documents"]),
                  "applied": False, "activated": False, "source_preserved": True}
        if not apply:
            return result
        grouped = {}
        for page in snapshot["pages"]:
            grouped.setdefault(int(page["document_id"]), []).append(page)
        for document in snapshot["documents"]:
            pages = grouped.get(int(document["id"]), [])
            if not any(page["usable"] and str(page.get("body") or "").strip() for page in pages):
                raise ValueError(f"Document {document['id']} has no usable pages; no replacement was built")
        try:
            segments.COLLECTION = target
            counts = {}
            if not snapshot["documents"]:
                segments._ensure_collection(client, 384)
            for document in snapshot["documents"]:
                document_id = int(document["id"])
                counts[str(document_id)] = segments.sync_pages(document_id, grouped[document_id])
                if counts[str(document_id)] <= 0 or not segments.has_segments(document_id):
                    raise RuntimeError(f"Replacement index verification failed for document {document_id}")
        finally:
            segments.COLLECTION = source
        current = material_snapshot(connection)
        if current["fingerprint"] != snapshot["fingerprint"]:
            raise RuntimeError("Source documents changed during rebuilding. Keep the current collection active and rebuild into another new target.")
        return {**result, "applied": True, "segments_by_document": counts,
                "next_step": f"Validate retrieval, then set MILVUS_COLLECTION={target} and restart the API. Retain {source} for rollback."}
    finally:
        if own_connection:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
    try:
        report = rebuild(args.target, apply=args.apply)
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
