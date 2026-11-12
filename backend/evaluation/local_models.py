"""Bounded actual local PDF/embedding/reranker smoke; no SQL, vector DB or LLM."""
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation.core import require


def smoke_local_models(*, run=False, components=("pdf", "retrieval"), corpus_path=None):
    require(components and set(components) <= {"pdf", "retrieval"}, "Choose PDF and/or retrieval components")
    report = {"schema": "citepath-local-model-smoke-v1", "status": "not_run", "components": {},
              "llm_invoked": False, "database_mutated": False, "formal_evaluation_run": False,
              "official_accepted": None, "limits": [
                  "This checks local component execution, not database persistence or Milvus retrieval.",
                  "Page accounting and one retrieval example do not establish semantic, mathematical or citation quality."]}
    if not run:
        return report
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / "backend/.env", override=False)
    started = time.perf_counter()
    report["started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        if "pdf" in components:
            from evaluation.integration import development_documents
            from ingest.pdf_reader import read_pdf
            corpus_path = Path(corpus_path or root / "data/mit-6.006-spring-2020/corpus.json")
            paths = development_documents(corpus_path)
            metadata = json.loads(corpus_path.read_text(encoding="utf-8"))
            documents = {document["lecture"]: document for document in metadata["documents"] if document["lecture"] in (2, 3)}
            results = []
            for lecture, path in sorted(paths.items()):
                pages = read_pdf(path.read_bytes())
                usable = [page["page_number"] for page in pages if page["usable"]]
                require(len(pages) == documents[lecture]["page_count"] and usable == documents[lecture]["teaching_pages"],
                        "Production PDF page accounting differs from the development corpus")
                results.append({"lecture": lecture, "original_page_count": len(pages), "usable_original_pages": usable,
                                "page_text_sha256": {str(page["page_number"]): hashlib.sha256((page["body"] or "").encode()).hexdigest() for page in pages}})
            report["components"]["pdf"] = {"status": "passed", "documents": results}
        if "retrieval" in components:
            from vector.segments import _embed, MODEL_NAME as embedding_model
            from vector.rerank import rerank, MODEL_NAME as reranker_model
            texts = ["A sequence interface represents an ordered collection of items.", "Today's weather is sunny."]
            vectors = _embed(texts)
            require(len(vectors) == 2 and all(len(vector) == 384 and all(math.isfinite(value) for value in vector) for vector in vectors),
                    "The production embedding model returned invalid vectors")
            ranked = rerank("What does a sequence interface represent?", [{"id": index, "text": text} for index, text in enumerate(texts)])
            require(len(ranked) == 2 and ranked[0]["id"] == 0 and all(math.isfinite(row["score"]) for row in ranked),
                    "The production reranker did not rank the direct development example first")
            report["components"]["retrieval"] = {"status": "passed", "embedding_model": embedding_model,
                "reranker_model": reranker_model, "vector_dimension": 384, "ranked_ids": [row["id"] for row in ranked],
                "scores": [row["score"] for row in ranked]}
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["failure_type"] = type(error).__name__
        report["failure_code"] = "local_model_smoke_failed_check_runtime_and_short_writable_cache_paths"
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report
