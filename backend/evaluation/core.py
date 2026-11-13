"""Evidence-driven metrics. Missing judgments remain unknown, never zero or pass."""
import hashlib
import json
import math
from datetime import datetime
from statistics import median

SCHEMA = "citepath-evaluation-v1"
VARIANTS = ("baseline", "full")
TARGET_COUNTS = {"mcq": 20, "short": 40, "evidence": 40, "workflow": 20}
PROHIBITED = ("third_round", "duplicate_scoring", "qa_score_changed")
AUDIT_FIELDS = ("clear", "source_supported", "answer_key_correct", "not_repeated")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def timestamp(value):
    require(isinstance(value, str), "A collection/freeze timestamp must be an ISO string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid collection/freeze timestamp") from error
    require(result.tzinfo is not None, "Collection/freeze timestamps must include a timezone")
    return result


def source_key(source):
    require(isinstance(source, dict), "A source must be an object")
    identifier = source.get("document_id")
    require(type(identifier) in (str, int) and str(identifier), "A source needs a document_id")
    number = source.get("page_number")
    require(type(number) is int and number > 0, "A source needs an original positive PDF page_number")
    return str(identifier), number


def valid_source(source, documents):
    key = source_key(source)
    document = documents.get(key[0])
    return bool(document and (not document.get("page_count") or key[1] <= document["page_count"])
                and (document.get("teaching_pages") is None or key[1] in document["teaching_pages"]))


def validate_dataset(data):
    require(isinstance(data, dict) and data.get("schema") == SCHEMA, "Unsupported evaluation schema")
    require(isinstance(data.get("evaluation_id"), str) and data["evaluation_id"], "evaluation_id is required")
    require(data.get("split") in ("development", "final"), "split must be development or final")
    require(type(data.get("synthetic")) is bool, "Declare whether the runs are synthetic")
    require(isinstance(data.get("documents"), list) and isinstance(data.get("items"), list), "documents/items must be arrays")
    documents = {}
    allowed = {2, 3} if data["split"] == "development" else {4, 6, 8}
    for document in data["documents"]:
        require(isinstance(document, dict), "A document must be an object")
        identifier = str(document.get("id") or "")
        require(identifier and identifier not in documents, "Document IDs must be unique and nonempty")
        require(document.get("lecture") in allowed, "Development and held-out lecture splits cannot be mixed")
        sha = document.get("sha256")
        require(isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), "Each original PDF needs its SHA-256")
        if document.get("page_count") is not None:
            require(type(document["page_count"]) is int and document["page_count"] > 0, "Invalid PDF page count")
        if document.get("teaching_pages") is not None:
            require(isinstance(document["teaching_pages"], list) and document["teaching_pages"]
                    and all(type(p) is int and 0 < p <= document.get("page_count", p) for p in document["teaching_pages"])
                    and len(set(document["teaching_pages"])) == len(document["teaching_pages"]), "Invalid teaching-page list")
        documents[identifier] = document
    ids = set()
    for item in data["items"]:
        require(isinstance(item, dict), "An item must be an object")
        identifier = item.get("id")
        require(isinstance(identifier, str) and identifier and identifier not in ids, "Item IDs must be unique nonempty strings")
        ids.add(identifier)
        require(item.get("kind") in TARGET_COUNTS, f"Unknown item kind: {item.get('kind')}")
        require(item.get("lecture") in allowed, "Every item must belong to the declared lecture split")
        require(isinstance(item.get("question"), str) and item["question"].strip(), "Each item needs a question/scenario")
        sources = item.get("sources") or []
        require(isinstance(sources, list), "Item sources must be an array")
        for source in sources:
            require(valid_source(source, documents), "Reference source points outside the frozen PDFs")
        if item["kind"] == "short":
            rubric = item.get("rubric")
            require(isinstance(rubric, list) and rubric and all(isinstance(p, str) and p.strip() for p in rubric), "Short answers require predefined rubric points")
            require(len({p.strip().casefold() for p in rubric}) == len(rubric), "Rubric points must be distinct")
            require(isinstance(item.get("response"), str), "Short-answer items need the actual student response")
        if item["kind"] == "mcq":
            options = item.get("options")
            require(isinstance(options, list) and len(options) == 4
                    and all(isinstance(option, str) and option.strip() for option in options)
                    and len({option.strip().casefold() for option in options}) == 4,
                    "MCQ items need four distinct option texts")
            require(isinstance(item.get("response"), str), "MCQ items need the actual selected response")
        predictions = item.get("predictions") or {}
        require(isinstance(predictions, dict) and not set(predictions) - set(VARIANTS), "Predictions must use baseline/full variant names")
        for variant, prediction in predictions.items():
            if prediction is None:
                continue
            require(isinstance(prediction, dict), "A prediction must be an object or null")
            require(prediction.get("synthetic") is not True or data["synthetic"],
                    "Synthetic observations cannot be imported into a real evaluation cohort")
            if item["kind"] in ("mcq", "short"):
                require(type(prediction.get("correct")) is bool, "A recorded grade must be a boolean")
            elif item["kind"] == "evidence":
                require(type(prediction.get("refused")) is bool and isinstance(prediction.get("answer"), str), "Evidence predictions need answer/refused")
                claims = prediction.get("claims")
                require(isinstance(claims, list), "Claims must be explicitly enumerated for human audit")
                claim_ids = set()
                for claim in claims:
                    require(isinstance(claim, dict) and isinstance(claim.get("id"), str) and claim["id"] not in claim_ids, "Claim IDs must be unique")
                    claim_ids.add(claim["id"])
                    require(isinstance(claim.get("text"), str) and claim["text"].strip(), "A claim needs its factual text")
                    require(isinstance(claim.get("citations"), list), "Claim citations must be an array (empty means missing)")
                    for source in claim["citations"]:
                        source_key(source)  # Out-of-corpus citations count as failures below.
            else:
                require(isinstance(prediction.get("runs"), list), "Workflow predictions need their actual runs")
                require(all(isinstance(run, dict) for run in prediction["runs"]), "Every workflow run must be an object")
                require(all(run.get("synthetic") is not True or data["synthetic"] for run in prediction["runs"]),
                        "Synthetic workflow runs cannot be formal observations")
                repeats = [run.get("repeat") for run in prediction["runs"]]
                require(all(type(r) is int and r in (1, 2, 3) for r in repeats) and len(repeats) == len(set(repeats)), "Workflow repeats must be unique 1, 2 or 3")
    return documents


def label_key(item, variant):
    return item["id"], "shared" if item["kind"] in ("mcq", "short") else variant


def empty_label(item, variant):
    result = {"item_id": item["id"], "variant": label_key(item, variant)[1]}
    if item["kind"] == "mcq":
        result.update(correct=None, supporting_pages=[])
    elif item["kind"] == "short":
        result.update(hits=None, supporting_pages=[])
    else:
        claims = ((item.get("predictions") or {}).get(variant) or {}).get("claims") or []
        result.update(supported=None, answer_correct=None, supporting_pages=[], reference_point_hits=None,
                      claims_complete=None, claim_support={claim["id"]: None for claim in claims},
                      irrelevant_citations=None)
    if item["kind"] in ("mcq", "short"):
        result["question_audit"] = {field: None for field in AUDIT_FIELDS}
    return result


def prepare_labels(data):
    validate_dataset(data)
    labels = []
    blind = []
    for item in data["items"]:
        if item["kind"] == "workflow":
            continue
        variants = ("shared",) if item["kind"] in ("mcq", "short") else VARIANTS
        for variant in variants:
            labels.append(empty_label(item, variant))
            record = {key: item[key] for key in ("id", "kind", "lecture", "question", "response", "options", "rubric", "sources", "reference_points") if key in item}
            record["variant"] = variant
            if item["kind"] == "evidence":
                predicted = ((item.get("predictions") or {}).get(variant) or {})
                record.update(answer=predicted.get("answer"), claims=predicted.get("claims"))
            blind.append(record)
    return ({"schema": SCHEMA, "dataset_sha256": digest(data), "annotator_id": None,
             "independent": False, "label_origin": "unassigned", "labels": labels},
            {"dataset_sha256": digest(data), "documents": data["documents"], "items": blind})


def _indexes(data, annotators, adjudication):
    items = {item["id"]: item for item in data["items"]}
    documents = {str(doc["id"]): doc for doc in data["documents"]}
    indices, names, attested = [], [], True
    for position, document in enumerate(annotators):
        require(document.get("dataset_sha256") == digest(data), "Annotations refer to a different frozen dataset")
        name = document.get("annotator_id")
        if name is None and document.get("independent") is not True:
            name = f"unassigned-{position + 1}"
        require(isinstance(name, str) and name and name not in names and not name.startswith("REPLACE_"), "Two distinct annotator identities are required")
        names.append(name)
        attested = attested and document.get("independent") is True and document.get("label_origin") == "human"
        indices.append(_label_index(document.get("labels"), items, documents))
    require(len(indices) <= 2, "Exactly two independent annotation files are supported")
    while len(indices) < 2:
        indices.append({})
        attested = False
    resolved = {}
    if adjudication:
        require(adjudication.get("dataset_sha256") == digest(data), "Adjudication refers to a different frozen dataset")
        require(adjudication.get("adjudicator_id"), "Record who resolved the disagreements")
        require(isinstance(adjudication.get("reviewed_by"), list)
                and set(names) <= set(adjudication["reviewed_by"]),
                "Both original annotators must be recorded in adjudication reviewed_by")
        resolved = _label_index(adjudication.get("labels"), items, documents)
        require(all(isinstance(label.get("reason"), str) and label["reason"].strip() for label in resolved.values()), "Every adjudication needs a reason")
    return indices, resolved, attested


def _label_index(labels, items, documents):
    require(isinstance(labels, list), "Human labels must be an array")
    result = {}
    for label in labels:
        require(isinstance(label, dict) and label.get("item_id") in items, "Unknown labeled item ID")
        item = items[label["item_id"]]
        variant = label.get("variant")
        require(variant in (("shared",) if item["kind"] in ("mcq", "short") else VARIANTS), "Invalid annotation variant")
        key = item["id"], variant
        require(key not in result, "Duplicate human label")
        for source in label.get("supporting_pages") or []:
            require(valid_source(source, documents), "Human supporting page is outside the frozen PDFs")
        if item["kind"] == "mcq":
            require(label.get("correct") is None or type(label["correct"]) is bool, "MCQ reference correctness must be boolean or null")
        elif item["kind"] == "short":
            _hits(label.get("hits"), len(item["rubric"]))
        elif item["kind"] == "evidence":
            require(label.get("supported") is None or type(label["supported"]) is bool, "Evidence support must be boolean or null")
            require(label.get("answer_correct") is None or type(label["answer_correct"]) is bool, "Answer correctness must be boolean or null")
            require(label.get("claims_complete") is None or type(label["claims_complete"]) is bool, "Claims audit must be boolean or null")
            _hits(label.get("reference_point_hits"), len(item.get("reference_points") or []))
            prediction = ((item.get("predictions") or {}).get(variant) or {})
            claims = {claim["id"]: claim for claim in prediction.get("claims") or []}
            support = label.get("claim_support") or {}
            require(isinstance(support, dict) and not set(support) - set(claims), "Human support labels name an unknown claim")
            require(all(value is None or type(value) is bool for value in support.values()), "Claim support must be boolean or null")
            irrelevant = label.get("irrelevant_citations")
            require(irrelevant is None or isinstance(irrelevant, list), "Irrelevant citations must be explicitly checked")
            seen = set()
            for source in irrelevant or []:
                claim = claims.get(source.get("claim_id"))
                require(claim is not None, "Irrelevant citation names an unknown claim")
                ref = source_key(source)
                require(any(source_key(citation) == ref for citation in claim["citations"]), "Irrelevant citation was not cited by the system")
                require((source["claim_id"], ref) not in seen, "Duplicate irrelevant-citation judgment")
                seen.add((source["claim_id"], ref))
        audit = label.get("question_audit") or {}
        require(isinstance(audit, dict) and not set(audit) - set(AUDIT_FIELDS), "Unknown generated-question audit criterion")
        require(all(value is None or type(value) is bool for value in audit.values()), "Question audit values must be booleans or null")
        result[key] = label
    return result


def _hits(value, total):
    require(value is None or isinstance(value, list), "Reference hits must be indexes or null")
    if value is not None:
        require(all(type(i) is int and 0 <= i < total for i in value) and len(value) == len(set(value)), "Invalid or duplicate reference-point index")


def _reference(key, indices, adjudications, disagreements):
    first, second = (index.get(key) for index in indices)
    if first is None or second is None:
        return None
    ignored = {"item_id", "variant", "reason"}
    def comparable(label):
        result = {key: value for key, value in label.items() if key not in ignored}
        for key in ("hits", "reference_point_hits"):
            if isinstance(result.get(key), list):
                result[key] = sorted(result[key])
        for key in ("supporting_pages", "irrelevant_citations"):
            if isinstance(result.get(key), list):
                result[key] = sorted(result[key], key=lambda value: json.dumps(value, sort_keys=True))
        return result
    if comparable(first) == comparable(second):
        return first
    disagreements.add(key)
    return adjudications.get(key)


def _ratio(hit, total, pending=0, threshold=None):
    value = hit / total if total and not pending else None
    return {"matched": hit, "total": total, "pending": pending, "value": value,
            "target": threshold, "target_met": None if value is None or threshold is None else value >= threshold}


def _freeze_problems(data):
    freeze = data.get("freeze") or {}
    problems = []
    if not all(freeze.get(key) for key in ("manifest_sha256", "created_at", "git_commit", "model")):
        return ["Frozen configuration and model identity are incomplete"]
    require(len(freeze["manifest_sha256"]) == 64
            and all(c in "0123456789abcdef" for c in freeze["manifest_sha256"]), "Invalid frozen manifest SHA-256")
    require(isinstance(freeze["git_commit"], str) and len(freeze["git_commit"]) == 40
            and all(c in "0123456789abcdef" for c in freeze["git_commit"]), "Invalid frozen Git commit")
    frozen_at = timestamp(freeze["created_at"])
    actual_policy = any(any(expected.get("policy") == "actual_grade_v1" for expected in (item.get("expected") or {}).values())
                        for item in data["items"] if item["kind"] == "workflow")
    protocol = data.get("evaluation_protocol") or {}
    if actual_policy and data["split"] == "final" and not data["synthetic"]:
        reviewers = protocol.get("reviewed_by")
        mapping = protocol.get("chapter_mapping_sha256")
        response_policy = protocol.get("response_policy_sha256")
        hashes_ok = (isinstance(mapping, str) and len(mapping) == 64
                     and all(character in "0123456789abcdef" for character in mapping)
                     and isinstance(response_policy, str) and len(response_policy) == 64
                     and all(character in "0123456789abcdef" for character in response_policy))
        two_human = (protocol.get("reviewed") is True and protocol.get("review_origin") == "human"
                     and isinstance(reviewers, list) and len(reviewers) == 2
                     and all(isinstance(value, str) and value.strip() for value in reviewers)
                     and len({value.strip().casefold() for value in reviewers}) == 2)
        single_approved = (protocol.get("reviewed") is True
                           and protocol.get("single_reviewer_approved") is True
                           and protocol.get("review_origin") == "single_reviewer_approved"
                           and isinstance(reviewers, list) and len(reviewers) == 1
                           and all(isinstance(value, str) and value.strip() for value in reviewers))
        if not ((two_human or single_approved) and hashes_ok):
            problems.append("Two human reviewers, or an explicitly approved single-reviewer deviation, must review the actual-grade protocol and freeze the chapter/fixture mapping")
    for item in data["items"]:
        for variant, prediction in (item.get("predictions") or {}).items():
            if prediction is None:
                continue
            if not prediction.get("collected_at") or not prediction.get("configuration_sha256"):
                problems.append(f"{item['id']}/{variant}: collection timestamp/configuration hash missing")
                continue
            require(timestamp(prediction["collected_at"]) >= frozen_at, "A prediction was collected before configuration freezing")
            require(prediction["configuration_sha256"] == freeze["manifest_sha256"], "A prediction uses a different frozen configuration")
            require(prediction.get("model") == freeze["model"], "Baseline and full predictions must use the frozen model")
            if freeze.get("provider"):
                require(prediction.get("provider") == freeze["provider"]
                        and prediction.get("base_url_sha256") == freeze.get("base_url_sha256"), "Collected provider or endpoint differs from freeze")
            if actual_policy and item["kind"] == "workflow" and data["split"] == "final" and not data["synthetic"]:
                require(prediction.get("chapter_mapping_sha256") == protocol.get("chapter_mapping_sha256"), "Workflow mapping differs from reviewed protocol")
                require(prediction.get("response_policy_sha256") == protocol.get("response_policy_sha256"), "Workflow responses differ from reviewed protocol")
    return problems


def evaluate(data, annotators=(), adjudication=None, usage=()):
    documents = validate_dataset(data)
    indices, resolutions, attested = _indexes(data, annotators, adjudication)
    pending_reasons = _freeze_problems(data)
    if not attested:
        pending_reasons.append("Two independent human annotation attestations are required")
    counts = {kind: sum(item["kind"] == kind for item in data["items"]) for kind in TARGET_COUNTS}
    if data["split"] == "final" and counts != TARGET_COUNTS:
        pending_reasons.append(f"Final cohort must contain exactly {TARGET_COUNTS}; observed {counts}")
    disagreements = set()
    variants = {}
    label_refs = {}
    for variant in VARIANTS:
        grades = {kind: {"hit": 0, "pending": 0, "false_passes": 0, "false_failures": 0} for kind in ("mcq", "short")}
        citation_hit = citation_total = citation_pending = missing_citations = invalid_citations = irrelevant = irrelevant_pending = 0
        answer_hit = answer_pending = 0
        coverage_hit = coverage_total = coverage_pending = support_total = unsupported_total = refusal_hit = refusal_pending = supported_refusals = answer_failures = 0
        audit_counts = {field: {"passed": 0, "failed": 0, "pending": 0} for field in AUDIT_FIELDS}
        workflow_runs = []
        for item in data["items"]:
            kind = item["kind"]
            prediction = (item.get("predictions") or {}).get(variant)
            if kind == "workflow":
                workflow_runs.extend(_workflow_runs(item, variant, prediction))
                continue
            key = label_key(item, variant)
            reference = _reference(key, indices, resolutions, disagreements)
            label_refs[key] = reference
            if kind in grades:
                for field in AUDIT_FIELDS:
                    judgment = ((reference or {}).get("question_audit") or {}).get(field)
                    audit_counts[field]["pending" if judgment is None else "passed" if judgment else "failed"] += 1
                truth = (reference or {}).get("correct") if kind == "mcq" else None
                if kind == "short" and reference and reference.get("hits") is not None:
                    truth = len(reference["hits"]) * 5 >= len(item["rubric"]) * 4
                if prediction is None or truth is None:
                    grades[kind]["pending"] += 1
                    continue
                predicted = prediction["correct"]
                grades[kind]["hit"] += predicted == truth
                grades[kind]["false_passes"] += predicted and not truth
                grades[kind]["false_failures"] += truth and not predicted
                continue
            if reference is None or reference.get("supported") is None:
                refusal_pending += 1
                answer_pending += 1
            elif reference["supported"]:
                support_total += 1
                if prediction is not None and prediction["refused"]:
                    supported_refusals += 1
                    answer_failures += 1
                elif prediction is None or reference.get("answer_correct") is None:
                    answer_pending += 1
                else:
                    answer_hit += reference["answer_correct"]
                    answer_failures += not reference["answer_correct"]
            else:
                unsupported_total += 1
                if prediction is None:
                    refusal_pending += 1
                    answer_pending += 1
                else:
                    refusal_hit += prediction["refused"]
                    answer_hit += prediction["refused"]
            points = item.get("reference_points") or []
            if reference and reference.get("supported"):
                coverage_total += len(points)
                if prediction is not None and prediction["refused"]:
                    pass  # A supported question refused is an answer failure, zero covered points.
                elif not points or reference.get("reference_point_hits") is None or prediction is None:
                    coverage_pending += max(1, len(points))
                else:
                    coverage_hit += len(reference["reference_point_hits"])
            if prediction is None:
                citation_pending += 1
                continue
            claims = prediction["claims"]
            if not reference or reference.get("claims_complete") is not True:
                citation_pending += 1
            if prediction["refused"] and claims:
                raise ValueError("A refusal cannot hide factual claims from citation review")
            if not prediction["refused"] and not claims:
                citation_pending += 1
            for claim in claims:
                citation_total += 1
                citations = claim["citations"]
                if not citations:
                    missing_citations += 1
                else:
                    usable = [source for source in citations if valid_source(source, documents)]
                    if len(usable) != len(citations):
                        invalid_citations += 1
                    if usable:
                        judgment = ((reference or {}).get("claim_support") or {}).get(claim["id"])
                        if judgment is None:
                            citation_pending += 1
                        else:
                            citation_hit += judgment
            if reference and reference.get("irrelevant_citations") is not None:
                irrelevant += len(reference["irrelevant_citations"])
            else:
                irrelevant_pending += 1
        workflow = _workflow_summary(workflow_runs, counts["workflow"])
        mcq = _ratio(grades["mcq"]["hit"], counts["mcq"], grades["mcq"]["pending"], 1.0)
        short = {**_ratio(grades["short"]["hit"], counts["short"], grades["short"]["pending"], .8),
                 "false_passes": grades["short"]["false_passes"], "false_failures": grades["short"]["false_failures"]}
        citation = {**_ratio(citation_hit, citation_total, citation_pending, .85),
                    "missing_citation_claims": missing_citations, "invalid_citation_claims": invalid_citations,
                    "irrelevant_citations_observed": irrelevant,
                    "irrelevant_citation_audits_pending": irrelevant_pending}
        variants[variant] = {
            "mcq_agreement": mcq, "short_agreement": short, "citation_support": citation,
            "answer_correctness": _ratio(answer_hit, counts["evidence"], answer_pending),
            "reference_answer_point_coverage": _ratio(coverage_hit, coverage_total, coverage_pending),
            "unsupported_refusal": {**_ratio(refusal_hit, unsupported_total, refusal_pending), "supported_questions_refused": supported_refusals,
                                    "supported_questions": support_total, "answer_failures": answer_failures},
            "generated_question_audit": audit_counts, "workflow": workflow,
            "usage": summarize_usage([row for row in usage if _context(row).get("evaluation_id") == data["evaluation_id"] and (_context(row).get("variant") or _context(row).get("system")) == variant]),
        }
    if data["split"] == "final":
        evidence = variants["full"]["unsupported_refusal"]
        if evidence["supported_questions"] != 30 or evidence["total"] != 10:
            pending_reasons.append("Final evidence set needs 30 supported and 10 unsupported questions after human adjudication")
    full = variants["full"]
    for variant, metrics in variants.items():
        if any(metrics[name]["value"] is None for name in ("mcq_agreement", "short_agreement", "citation_support")):
            pending_reasons.append(f"{variant}: model runs or human labels are incomplete")
        if any(values["pending"] for values in metrics["generated_question_audit"].values()):
            pending_reasons.append(f"{variant}: generated-question audits are incomplete")
        if metrics["reference_answer_point_coverage"]["pending"] or metrics["unsupported_refusal"]["pending"]:
            pending_reasons.append(f"{variant}: descriptive answer/refusal judgments are incomplete")
        if metrics["answer_correctness"]["pending"] or metrics["citation_support"]["irrelevant_citation_audits_pending"]:
            pending_reasons.append(f"{variant}: answer correctness or citation relevance audits are incomplete")
        if metrics["workflow"]["runs_completed"] != counts["workflow"] * 3:
            pending_reasons.append(f"{variant}: three workflow repeats per scenario are required")
    targets = [full["mcq_agreement"]["target_met"], full["short_agreement"]["target_met"],
               full["citation_support"]["target_met"], full["workflow"]["target_met"]]
    if any(value is None for value in targets):
        pending_reasons.append("Final model runs, human judgments or workflow observations are incomplete")
    unresolved = [list(key) for key in sorted(disagreements) if key not in resolutions]
    if unresolved:
        pending_reasons.append("Human annotation disagreements still need adjudication")
    eligible = not pending_reasons and data["split"] == "final" and not data["synthetic"]
    prohibited_errors = [
        {"variant": variant, **row}
        for variant, metrics in variants.items()
        for row in metrics["workflow"]["prohibited_errors"]
    ]
    return {
        "schema": SCHEMA, "evaluation_id": data["evaluation_id"], "dataset_sha256": digest(data),
        "split": data["split"], "synthetic": data["synthetic"], "item_counts": counts,
        "status": "complete" if eligible else "pending" if pending_reasons else "development_only",
        "official_accepted": all(targets) and not prohibited_errors if eligible else None,
        "prohibited_errors": prohibited_errors,
        "pending_reasons": list(dict.fromkeys(pending_reasons)), "annotation_disagreements": len(disagreements),
        "unresolved_disagreements": unresolved, "variants": variants,
        "comparison": comparison(variants),
        "shared_first_round_usage": summarize_usage([
            row for row in usage if _context(row).get("evaluation_id") == data["evaluation_id"]
            and (_context(row).get("variant") or _context(row).get("system")) == "shared_first_round"]),
        "unscoped_usage_records": sum(_context(row).get("evaluation_id") != data["evaluation_id"] for row in usage),
        "limits": ["Human independence is attested, not technically provable.",
                   "Model-invocation counts do not enumerate internal SDK retries.",
                   "Metrics without a proposal threshold are descriptive only; unknown evidence is not zero."],
    }


def _workflow_runs(item, variant, prediction):
    expected = (item.get("expected") or {}).get(variant) or {}
    expected_actions = expected.get("actions") or []
    require(isinstance(expected_actions, list)
            and all(isinstance(action, str) and action.strip() for action in expected_actions),
            "Expected workflow actions must be an ordered list of concrete step names")
    observed = {run["repeat"]: run for run in (prediction or {}).get("runs") or []}
    result = []
    for repeat in (1, 2, 3):
        run = observed.get(repeat)
        rule = expected
        if expected.get("policy") is not None:
            from evaluation.protocol import POLICY, actual_grade_expectation
            require(expected["policy"] == POLICY, "Unknown frozen workflow policy")
            rule = actual_grade_expectation(item, variant, (run or {}).get("observed_rounds")) or {}
        expected_actions = rule.get("actions") or []
        if run and "scenario_match" in run:
            require(run["scenario_match"] is None or type(run["scenario_match"]) is bool,
                    "Scenario-match evidence must be a boolean or unknown")
        complete = bool(run and rule.get("transitions") and rule.get("final_state")
                        and (not expected.get("policy") or type(run.get("passing_threshold")) in (int, float))
                        and run.get("observation_status") not in {"not_run", "failed", "uncertain"}
                        and isinstance(run.get("transitions"), list) and run.get("final_state")
                        and (not expected_actions or isinstance(run.get("actions"), list))
                        and all(type(run.get(name)) is bool for name in PROHIBITED))
        prohibited = [name for name in PROHIBITED if run and run.get(name) is True]
        if run and type(run.get("round_count")) is int and run["round_count"] > (1 if variant == "baseline" else 2):
            if "third_round" not in prohibited:
                prohibited.append("third_round" if run["round_count"] > 2 else "baseline_generated_followup")
        passed = None
        if complete:
            passed = (run["transitions"] == rule["transitions"] and run["final_state"] == rule["final_state"]
                      and (not expected_actions or run["actions"] == expected_actions) and not prohibited
                      and run.get("scenario_match") is not False and rule.get("grade_consistent") is not False)
            if expected.get("policy"):
                passed = passed and run["passing_threshold"] == item["scenario"]["passing_threshold"]
            if "passed" in run:
                require(type(run["passed"]) is bool and run["passed"] == passed, "Self-reported workflow success contradicts its trace")
        result.append({"item_id": item["id"], "repeat": repeat, "passed": passed,
                       "prohibited_errors": prohibited, **{key: (run or {}).get(key) for key in (
                           "round_count", "grading_feedback_latency_ms", "model_calls", "input_tokens",
                           "output_tokens", "estimated_cost", "cost_currency")}})
    return result


def _workflow_summary(runs, total):
    repeats = []
    for repeat in (1, 2, 3):
        subset = [run for run in runs if run["repeat"] == repeat]
        passed = sum(run["passed"] is True for run in subset)
        pending = sum(run["passed"] is None for run in subset)
        repeats.append({"repeat": repeat, "passed": passed, "total": total, "pending": pending,
                        "failed": sum(run["passed"] is False for run in subset)})
    prohibited = [{"item_id": row["item_id"], "repeat": row["repeat"], "errors": row["prohibited_errors"]} for row in runs if row["prohibited_errors"]]
    by_item = {}
    for run in runs:
        by_item.setdefault(run["item_id"], []).append(run)
    scenarios = []
    for item_id, observations in by_item.items():
        failed = any(run["passed"] is False for run in observations)
        observed = sum(run["passed"] is not None for run in observations)
        passed = len(observations) == 3 and all(run["passed"] is True for run in observations)
        scenarios.append({"item_id": item_id, "status": "failed" if failed else "passed" if passed else "pending",
                          "repeats_observed": observed, "repeats_expected": 3})
    scenario_passes = sum(row["status"] == "passed" for row in scenarios)
    scenario_failures = sum(row["status"] == "failed" for row in scenarios)
    scenario_pending = sum(row["status"] == "pending" for row in scenarios)
    complete = total == 20 and len(scenarios) == total and all(run["passed"] is not None for run in runs)
    return {"repeats": repeats,
            "scenario_results": scenarios,
            "scenarios_passed": scenario_passes, "scenarios_failed": scenario_failures, "scenarios_pending": scenario_pending,
            "target": "at least 18 of 20 scenarios pass all three repeats; zero prohibited errors",
            "target_met": scenario_passes >= 18 and not prohibited if complete else None,
            "prohibited_errors": prohibited, "runs_completed": sum(run["passed"] is not None for run in runs),
            "runs_failed": sum(run["passed"] is False for run in runs),
            "unclassified_round_count_runs": sum(run["round_count"] not in (1, 2) for run in runs),
            "usage_by_round_count": {str(rounds): summarize_usage([run for run in runs if run["round_count"] == rounds]) for rounds in (1, 2)},
            "grading_feedback_latency_ms": {str(rounds): distribution([run["grading_feedback_latency_ms"] for run in runs if run["round_count"] == rounds]) for rounds in (1, 2)}}


def distribution(values):
    known = [value for value in values if type(value) in (int, float) and math.isfinite(value) and value >= 0]
    ordered = sorted(known)
    return {"observations": len(known), "unknown": len(values) - len(known),
            "median": median(known) if known else None,
            "p95": ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else None}


def _context(row):
    return {**(row.get("context") or {}), **row}


def summarize_usage(rows):
    result = {"records": len(rows), "latency_ms": distribution([row.get("latency_ms") for row in rows]),
              "successful_calls": sum(row.get("status") == "ok" for row in rows),
              "failed_calls": sum(row.get("status") == "error" for row in rows)}
    for field in ("model_calls", "input_tokens", "output_tokens", "estimated_cost"):
        values = [row.get(field) for row in rows]
        known = [value for value in values if type(value) in (int, float) and math.isfinite(value) and value >= 0]
        result[field] = {"known_subtotal": sum(known), "unknown_records": len(values) - len(known),
                         "total": sum(known) if values and len(known) == len(values) else None}
    currencies = {row.get("cost_currency") for row in rows if row.get("estimated_cost") is not None}
    result["cost_currency"] = next(iter(currencies)) if len(currencies) == 1 else None
    if len(currencies) != 1 or None in currencies:
        result["estimated_cost"]["total"] = None
    return result


def comparison(variants):
    names = ("mcq_agreement", "short_agreement", "citation_support", "answer_correctness", "reference_answer_point_coverage", "unsupported_refusal")
    result = {}
    for name in names:
        left = variants["baseline"][name]["value"]
        right = variants["full"][name]["value"]
        result[name] = {"baseline": left, "full": right, "difference": right - left if left is not None and right is not None else None}
    return result
