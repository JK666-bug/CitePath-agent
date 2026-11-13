"""Descriptive single-reviewer pilot for the formal evaluation inputs.

This tool deliberately does NOT produce an official evaluation result. It reads
one completed human annotation sheet and reports descriptive label coverage and
rates. `official_accepted` stays null because the proposal requires two
independent human reviewers and adjudication.

Usage:
    python tools/single_reviewer_pilot.py dataset.json annotator-a.json output.json
"""
import json
import sys
from pathlib import Path

DATASET_VARIANTS = {"mcq": ("shared",), "short": ("shared",), "evidence": ("baseline", "full")}


def ratio(hit, total):
    return None if not total else hit / total


def audit_stats(labels):
    keys = ("clear", "source_supported", "answer_key_correct", "not_repeated")
    total = {key: 0 for key in keys}
    passed = {key: 0 for key in keys}
    for label in labels:
        audit = label.get("question_audit") or {}
        for key in keys:
            if isinstance(audit.get(key), bool):
                total[key] += 1
                passed[key] += int(audit[key])
    return {key: {"known": total[key], "passed": passed[key],
                  "rate": ratio(passed[key], total[key])} for key in keys}


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: single_reviewer_pilot.py <dataset.json> <annotator.json> <output.json>")
    dataset_path, annotation_path, output_path = map(Path, sys.argv[1:])
    dataset = json.loads(dataset_path.read_text(encoding="utf-8-sig"))
    annotation = json.loads(annotation_path.read_text(encoding="utf-8-sig"))
    items = {item["id"]: item for item in dataset["items"]}

    labels = annotation.get("labels") or []
    by_key = {}
    for label in labels:
        key = (label.get("item_id"), label.get("variant"))
        by_key[key] = label

    expected = sum(len(DATASET_VARIANTS.get(item["kind"], ())) for item in dataset["items"])
    completed = 0
    mcq, short, evidence = [], [], []
    for label in labels:
        item = items.get(label.get("item_id"))
        if item is None:
            continue
        kind = item["kind"]
        if kind == "mcq" and isinstance(label.get("correct"), bool):
            completed += 1
            mcq.append(label)
        elif kind == "short" and isinstance(label.get("hits"), list):
            completed += 1
            short.append(label)
        elif kind == "evidence" and isinstance(label.get("supported"), bool):
            completed += 1
            evidence.append(label)

    mcq_correct = sum(1 for label in mcq if label.get("correct") is True)
    short_rows = []
    for label in short:
        item = items[label["item_id"]]
        total = len(item.get("rubric") or [])
        hits = label.get("hits") or []
        short_rows.append((len(hits), total, total > 0 and len(hits) * 5 >= total * 4))
    short_passed = sum(1 for _, _, passed in short_rows if passed)
    short_points = sum(hits / total for hits, total, _ in short_rows if total)

    claim_total = claim_supported = 0
    ref_hits = ref_total = 0
    supported_count = answer_correct_count = claims_complete_count = irrelevant = 0
    for label in evidence:
        item = items[label["item_id"]]
        supported_count += int(label.get("supported") is True)
        answer_correct_count += int(label.get("answer_correct") is True)
        claims_complete_count += int(label.get("claims_complete") is True)
        claims = label.get("claim_support") or {}
        if isinstance(claims, dict):
            claim_total += len(claims)
            claim_supported += sum(1 for value in claims.values() if value is True)
        reference_points = item.get("reference_points") or []
        hits = label.get("reference_point_hits") or []
        if reference_points:
            ref_total += len(reference_points)
            ref_hits += len([index for index in hits if type(index) is int and 0 <= index < len(reference_points)])
        if isinstance(label.get("irrelevant_citations"), list):
            irrelevant += len(label["irrelevant_citations"])

    result = {
        "schema": "citepath-single-reviewer-pilot-v1",
        "status": "single_reviewer_pilot",
        "mode": "descriptive_not_official",
        "official_accepted": None,
        "reviewer_count": 1,
        "annotator_id": annotation.get("annotator_id"),
        "label_origin": annotation.get("label_origin"),
        "independent_attested": annotation.get("independent") is True,
        "dataset_sha256": dataset.get("sha256") or annotation.get("dataset_sha256"),
        "label_completion": {"completed": completed, "expected": expected,
                             "rate": ratio(completed, expected)},
        "mcq": {"n": len(mcq), "correct": mcq_correct,
                "accuracy": ratio(mcq_correct, len(mcq))},
        "short": {"n": len(short), "passed": short_passed,
                  "pass_rate": ratio(short_passed, len(short)),
                  "mean_point_coverage": ratio(short_points, len(short_rows))},
        "evidence": {"n": len(evidence),
                     "supported": supported_count, "supported_rate": ratio(supported_count, len(evidence)),
                     "answer_correct": answer_correct_count,
                     "answer_correct_rate": ratio(answer_correct_count, len(evidence)),
                     "claims_complete": claims_complete_count,
                     "claims_complete_rate": ratio(claims_complete_count, len(evidence)),
                     "claim_support_rate": ratio(claim_supported, claim_total),
                     "reference_point_coverage": ratio(ref_hits, ref_total),
                     "irrelevant_citations": irrelevant},
        "question_audit": {"mcq": audit_stats(mcq), "short": audit_stats(short)},
        "limitations": [
            "Single reviewer: no inter-annotator agreement and no adjudication.",
            "Official acceptance still requires two independent human reviewers.",
            "Descriptive rates are not model quality targets and cannot be reported as official results.",
        ],
    }
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "official_accepted": None,
                      "label_completion": result["label_completion"],
                      "output": str(output_path)}))


if __name__ == "__main__":
    main()
