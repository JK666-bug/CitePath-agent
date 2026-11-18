"""Explicit, resumable collection of production QA outputs, never human judgments."""
import copy
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation.core import VARIANTS, _freeze_problems, digest, timestamp, validate_dataset
from evaluation.integration import ApiClient, local_api_url


QA_POLICY = "production_qa_shared_v1"
CONFIG_SCHEMA = "citepath-evidence-runtime-v1"
CHECKPOINT_SCHEMA = "citepath-evidence-checkpoint-v1"


class EvidenceFailure(RuntimeError):
    """Only fixed codes may enter the separate collection journal."""


def _require(condition, code):
    if not condition:
        raise EvidenceFailure(code)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _keys(value, expected, code):
    _require(isinstance(value, dict) and set(value) == set(expected), code)


def _configuration(data, config):
    _keys(config, ("schema", "manifest_path", "qa_policy", "variants"), "invalid_runtime_configuration")
    _require(config["schema"] == CONFIG_SCHEMA and config["qa_policy"] == QA_POLICY, "unsupported_qa_policy")
    _keys(config["variants"], VARIANTS, "both_variants_required")
    freeze = data.get("freeze") or {}
    _require(all(freeze.get(key) for key in ("manifest_sha256", "created_at", "git_commit", "model", "provider", "base_url_sha256")),
             "complete_frozen_identity_required")
    _require(_sha(freeze["manifest_sha256"]) and _sha(freeze["base_url_sha256"]), "invalid_frozen_identity")
    _require(timestamp(freeze["created_at"]) <= datetime.now(timezone.utc), "freeze_timestamp_is_in_the_future")
    _require(not _freeze_problems(data), "incomplete_existing_prediction_metadata")
    manifest_path = Path(config["manifest_path"]).resolve()
    raw = manifest_path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == freeze["manifest_sha256"], "frozen_manifest_hash_mismatch")
    manifest = json.loads(raw)
    _require(all(manifest.get(key) == freeze[key] for key in ("created_at", "git_commit", "provider", "model", "base_url_sha256")),
             "frozen_manifest_identity_mismatch")
    _require(manifest.get("working_tree_dirty") is False and isinstance(manifest.get("installed_packages"), dict)
             and manifest["installed_packages"] and isinstance(manifest.get("python"), str), "complete_clean_runtime_manifest_required")
    sources = manifest.get("source_sha256")
    _require(isinstance(sources, dict) and sources and all(isinstance(key, str) and _sha(value) for key, value in sources.items()),
             "frozen_source_inventory_required")
    documents = {str(doc["id"]): doc for doc in data["documents"]}
    _require(documents and all(type(doc.get("page_count")) is int for doc in documents.values()), "frozen_document_page_counts_required")
    safe = {"schema": CONFIG_SCHEMA, "manifest_path": str(manifest_path), "qa_policy": QA_POLICY, "variants": {}}
    courses = set()
    for variant in VARIANTS:
        spec = config["variants"][variant]
        _keys(spec, ("api_url", "course_id", "username_env", "password_env", "documents"), "invalid_variant_configuration")
        origin = local_api_url(spec["api_url"])
        _require(type(spec["course_id"]) is int and spec["course_id"] > 0, "invalid_course_id")
        # Local URL aliases and multiple API workers may share the same database.
        course_key = spec["course_id"]
        _require(course_key not in courses, "separate_variant_courses_required")
        courses.add(course_key)
        for name in ("username_env", "password_env"):
            _require(isinstance(spec[name], str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", spec[name]), "credentials_must_use_environment_names")
        _require(spec["username_env"] != spec["password_env"], "distinct_credential_variables_required")
        _require(isinstance(spec["documents"], list), "invalid_document_mapping")
        mapped, runtime_ids, normalized = set(), set(), []
        for mapping in spec["documents"]:
            _keys(mapping, ("frozen_document_id", "runtime_document_id", "sha256", "page_count"), "invalid_document_mapping")
            frozen_id = str(mapping["frozen_document_id"])
            document = documents.get(frozen_id)
            runtime_id = mapping["runtime_document_id"]
            _require(document is not None and frozen_id not in mapped and type(runtime_id) is int and runtime_id > 0 and runtime_id not in runtime_ids,
                     "invalid_or_duplicate_document_mapping")
            _require(mapping["sha256"] == document["sha256"] and type(mapping["page_count"]) is int and mapping["page_count"] == document["page_count"],
                     "document_mapping_does_not_match_frozen_pdf")
            mapped.add(frozen_id)
            runtime_ids.add(runtime_id)
            normalized.append({**mapping, "frozen_document_id": frozen_id})
        _require(mapped == set(documents), "complete_frozen_corpus_mapping_required")
        safe["variants"][variant] = {**spec, "api_url": origin, "documents": sorted(normalized, key=lambda doc: doc["frozen_document_id"])}
    return safe, manifest


def _runtime(client, spec, manifest):
    observed = client.request("GET", f"/api/courses/{spec['course_id']}/evaluation/runtime")
    _require(isinstance(observed, dict) and observed.get("schema") == "citepath-evaluation-runtime-v1", "invalid_runtime_attestation")
    _require(observed.get("qa_policy") == QA_POLICY and observed.get("course_id") == spec["course_id"], "runtime_course_or_qa_policy_mismatch")
    _require(all(observed.get(key) == manifest.get(key) for key in ("provider", "model", "api_version", "base_url_sha256", "source_sha256", "model_cost_configuration", "retrieval_configuration")),
             "runtime_configuration_differs_from_freeze")
    _require(observed.get("python") == manifest["python"]
             and observed.get("runtime_packages_sha256") == digest(manifest["installed_packages"]),
             "runtime_packages_differ_from_freeze")
    rows = observed.get("documents")
    _require(isinstance(rows, list) and all(isinstance(row, dict) and type(row.get("id")) is int for row in rows), "invalid_runtime_document_attestation")
    actual = {row["id"]: row for row in rows}
    expected = {row["runtime_document_id"]: row for row in spec["documents"]}
    _require(len(actual) == len(rows) and set(actual) == set(expected), "runtime_corpus_differs_from_mapping")
    for identifier, mapping in expected.items():
        row = actual[identifier]
        _require(row.get("sha256") == mapping["sha256"] and type(row.get("page_count")) is int
                 and row["page_count"] == mapping["page_count"] and row.get("ingest_status") == "complete"
                 and row.get("is_active") is True, "runtime_document_not_ready_or_checksum_mismatch")


def _prediction(response, item, variant, spec, freeze, synthetic, latency_ms):
    _require(isinstance(response, dict) and isinstance(response.get("answer"), str)
             and type(response.get("refused")) is bool and response.get("course_id") == spec["course_id"]
             and response.get("question") == item["question"], "invalid_qa_response")
    _require(type(response.get("qa_id")) is int and response["qa_id"] > 0, "saved_qa_record_required")
    cited = response.get("cited_pages")
    _require(isinstance(cited, list), "invalid_qa_citations")
    mapping = {row["runtime_document_id"]: row["frozen_document_id"] for row in spec["documents"]}
    frozen_ids = set(mapping.values())
    citations = []
    for source in cited:
        _require(isinstance(source, dict) and type(source.get("document_id")) is int
                 and type(source.get("page_number")) is int and source["page_number"] > 0, "invalid_qa_citation_coordinates")
        runtime_id = source["document_id"]
        frozen_id = mapping.get(runtime_id)
        if frozen_id is None:
            # Preserve an invalid citation as invalid evidence rather than dropping it.
            frozen_id = "unmapped-runtime-document-" + str(runtime_id)
            while frozen_id in frozen_ids:
                frozen_id = "unmapped-" + frozen_id
        citation = {"document_id": frozen_id, "page_number": source["page_number"]}
        if citation not in citations:
            citations.append(citation)
    answer, refused = response["answer"], response["refused"]
    _require(answer.strip(), "empty_qa_answer")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", answer) if part.strip()]
    claims = [] if refused else [{"id": f"claim-{number}", "text": part, "citations": copy.deepcopy(citations)}
                                for number, part in enumerate(paragraphs, 1)]
    return {"answer": answer, "refused": refused, "claims": claims,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "configuration_sha256": freeze["manifest_sha256"], "model": freeze["model"],
            "provider": freeze["provider"], "base_url_sha256": freeze["base_url_sha256"],
            "collector": "production_qa_http", "variant": variant, "qa_policy": QA_POLICY,
            "qa_id": response["qa_id"], "synthetic": synthetic, "latency_ms": latency_ms,
            "human_review_required": True, "claim_segmentation": "verbatim_paragraph_candidates",
            "citation_assignment": "answer_level_candidates_require_human_review",
            "observed_answer_citations": citations,
            "refusal_text_requires_claim_review": refused,
            "external_sources_returned": bool(response.get("web_sources"))}


def _write_once(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect_evidence(data, config, *, run=False, checkpoint_dir=None, client_factory=ApiClient):
    """Return a new dataset, safe report and content-free journal.

    Both variants use production QA deliberately, on separate dedicated courses.
    This records a shared-QA comparison, not an invented retrieval ablation.
    Resume always takes the original dataset and the same runtime configuration.
    An intent without a completed output is uncertain and is never replayed.
    """
    updated = copy.deepcopy(data)
    synthetic = bool(data.get("synthetic")) or client_factory is not ApiClient
    report = {"schema": "citepath-evidence-collection-report-v1", "status": "not_run",
              "synthetic": synthetic, "official_accepted": None, "formal_evaluation_completed": False,
              "inference_requested": False, "completed_predictions": 0, "resumed_predictions": 0,
              "limits": ["Production QA policy is shared by baseline and full; this does not measure a QA ablation.",
                         "Paragraph boundaries and answer-level candidate citations need independent human review.",
                         "The API refusal flag is an observation, not a judgment that refusal is correct.",
                         "Dedicated courses retain QA conversation history; keep them isolated from other runs."]}
    result = {"dataset": updated, "report": report, "journal": []}
    if run is not True:
        return result
    if synthetic:
        updated["synthetic"] = True
    clients = {}
    try:
        validate_dataset(data)
        evidence = [item for item in data["items"] if item["kind"] == "evidence"]
        _require(evidence, "no_evidence_items")
        _require(all((item.get("predictions") or {}).get(variant) is None for item in evidence for variant in VARIANTS),
                 "existing_predictions_cannot_be_overwritten")
        safe, manifest = _configuration(data, config)
        _require(checkpoint_dir is not None, "checkpoint_directory_required")
        directory = Path(checkpoint_dir).resolve()
        # Collection must never mutate the distributed preparation/final cohorts.
        protected = Path(__file__).resolve().parents[2] / "evaluation_assets"
        _require(directory != protected and protected not in directory.parents, "checkpoints_must_be_outside_evaluation_assets")
        directory.mkdir(parents=True, exist_ok=True)
        binding = {"schema": CHECKPOINT_SCHEMA, "dataset_sha256": digest(data), "config_sha256": digest(safe), "synthetic": synthetic}
        binding_path = directory / "binding.json"
        if binding_path.exists():
            _require(_read(binding_path) == binding, "checkpoint_dataset_or_configuration_mismatch")
        else:
            _write_once(binding_path, binding)
        report.update(dataset_sha256=binding["dataset_sha256"], config_sha256=binding["config_sha256"], qa_policy=QA_POLICY)
        pending = []
        updated_by_id = {item["id"]: item for item in updated["items"]}
        for variant in VARIANTS:
            for item in evidence:
                operation = digest([item["id"], variant])
                intent_path, output_path = directory / (operation + ".intent.json"), directory / (operation + ".output.json")
                if output_path.exists():
                    saved = _read(output_path)
                    _require(intent_path.exists() and saved.get("binding") == binding and saved.get("item_id") == item["id"]
                             and saved.get("variant") == variant and digest(saved.get("prediction")) == saved.get("prediction_sha256"),
                             "checkpoint_completed_output_mismatch")
                    prediction = saved["prediction"]
                    _require(prediction.get("synthetic") is synthetic and all(prediction.get(key) == data["freeze"][key]
                             for key in ("provider", "model", "base_url_sha256"))
                             and prediction.get("configuration_sha256") == data["freeze"]["manifest_sha256"]
                             and timestamp(prediction["collected_at"]) >= timestamp(data["freeze"]["created_at"]),
                             "checkpoint_prediction_identity_mismatch")
                    updated_by_id[item["id"]].setdefault("predictions", {})[variant] = copy.deepcopy(prediction)
                    report["resumed_predictions"] += 1
                    result["journal"].append({"item_id": item["id"], "variant": variant, "status": "resumed", "prediction_sha256": saved["prediction_sha256"]})
                else:
                    _require(not intent_path.exists(), "uncertain_request_requires_manual_reconciliation")
                    pending.append((variant, item, intent_path, output_path))
        if pending:
            credentials = {}
            for variant in VARIANTS:
                spec = safe["variants"][variant]
                username, password = os.environ.get(spec["username_env"], ""), os.environ.get(spec["password_env"], "")
                _require(username and password, "runtime_credentials_missing")
                _require(username.startswith(("citepath_eval_", "citepath_it_")), "dedicated_runtime_account_required")
                credentials[variant] = (username, password)
            # Verify both runtimes before sending any evidence question.
            for variant in VARIANTS:
                spec = safe["variants"][variant]
                client = clients[variant] = client_factory(spec["api_url"])
                username, password = credentials[variant]
                user = client.request("POST", "/api/login", {"username": username, "password": password})
                _require(isinstance(user, dict) and user.get("username") == username, "runtime_login_identity_mismatch")
                _runtime(client, spec, manifest)
            for variant, item, intent_path, output_path in pending:
                spec, client = safe["variants"][variant], clients[variant]
                _runtime(client, spec, manifest)
                intent = {"binding": binding, "item_id": item["id"], "variant": variant,
                          "question_sha256": digest(item["question"]), "created_at": datetime.now(timezone.utc).isoformat()}
                _write_once(intent_path, intent)
                report["inference_requested"] = True
                started = time.perf_counter()
                response = client.request("POST", f"/api/courses/{spec['course_id']}/questions",
                                          {"question": item["question"],
                                            "document_ids": [row["runtime_document_id"] for row in spec["documents"]],
                                            "include_web": False, "evaluation_context": {
                                              "evaluation_id": data["evaluation_id"], "system": variant, "item_id": item["id"]}})
                prediction = _prediction(response, item, variant, spec, data["freeze"], synthetic,
                                         round((time.perf_counter() - started) * 1000))
                saved = {"binding": binding, "item_id": item["id"], "variant": variant,
                         "prediction": prediction, "prediction_sha256": digest(prediction)}
                _write_once(output_path, saved)
                updated_by_id[item["id"]].setdefault("predictions", {})[variant] = copy.deepcopy(prediction)
                result["journal"].append({"item_id": item["id"], "variant": variant, "status": "collected", "prediction_sha256": saved["prediction_sha256"]})
                report["completed_predictions"] += 1
        validate_dataset(updated)
        report["status"] = "completed"
    except (Exception, KeyboardInterrupt) as error:
        report["status"] = "blocked" if isinstance(error, EvidenceFailure) and str(error) == "runtime_credentials_missing" else "failed"
        report["failure"] = {"type": type(error).__name__, "code": str(error) if isinstance(error, EvidenceFailure) else "evidence_collection_failed"}
    finally:
        for client in clients.values():
            try:
                client.request("POST", "/api/logout")
            except Exception:
                pass
    return result
