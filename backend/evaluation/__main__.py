"""Offline, explicit-evidence evaluation CLI. No command invents human judgments."""
import argparse
import copy
import json
import sys
from pathlib import Path

from evaluation.core import (SCHEMA, TARGET_COUNTS, VARIANTS, _indexes, _reference,
                             digest, evaluate, prepare_labels, require, validate_dataset)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {value}")))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def adjudication_template(data, annotators):
    require(len(annotators) == 2, "Provide the two independently completed annotation files")
    validate_dataset(data)
    indices, _, _ = _indexes(data, annotators, None)
    keys = set(indices[0]) | set(indices[1])
    disagreements, records = set(), []
    for key in sorted(keys):
        _reference(key, indices, {}, disagreements)
        if key in disagreements:
            first = indices[0][key]
            record = copy.deepcopy(first)
            record["reason"] = ""
            records.append({"item_id": key[0], "variant": key[1],
                            "annotator_a": indices[0][key], "annotator_b": indices[1][key]})
    # Resolutions deliberately remain empty: neither member's answer is selected automatically.
    template = {"schema": SCHEMA, "dataset_sha256": digest(data),
                "adjudicator_id": None,
                "reviewed_by": [document.get("annotator_id") for document in annotators],
                "labels": []}
    return template, records


def import_predictions(data, recorded):
    require(recorded.get("dataset_sha256") == digest(data), "Recorded predictions belong to a different dataset snapshot")
    require(isinstance(recorded.get("records"), list), "Prediction records must be an array")
    updated = copy.deepcopy(data)
    items = {item["id"]: item for item in updated["items"]}
    seen = set()
    for row in recorded["records"]:
        require(isinstance(row, dict), "A prediction record must be an object")
        key = row.get("item_id"), row.get("variant")
        require(key[0] in items and key[1] in VARIANTS and key not in seen, "Unknown or duplicate prediction record")
        seen.add(key)
        require(isinstance(row.get("prediction"), dict), "A collected prediction must be an object")
        predictions = items[key[0]].setdefault("predictions", {})
        require(predictions.get(key[1]) is None, "A saved prediction cannot be overwritten; create a new named evaluation cohort")
        predictions[key[1]] = copy.deepcopy(row["prediction"])
    validate_dataset(updated)
    # Reject mismatched model/configuration/times now, not after annotation work.
    from evaluation.core import _freeze_problems
    problems = _freeze_problems(updated)
    require(not problems, "Freeze and stamp recorded predictions before importing: " + "; ".join(problems))
    return updated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a dataset without scoring or model calls")
    validate.add_argument("dataset", type=Path)
    labels = commands.add_parser("labels", help="Prepare two blank independent annotation files and blind work items")
    labels.add_argument("dataset", type=Path)
    labels.add_argument("--output-dir", type=Path, required=True)
    adjudication = commands.add_parser("adjudication", help="List disagreements without auto-selecting an annotator")
    adjudication.add_argument("dataset", type=Path)
    adjudication.add_argument("--annotator", action="append", type=Path, required=True)
    adjudication.add_argument("--output-dir", type=Path, required=True)
    score = commands.add_parser("score", help="Compute evidence-driven metrics; missing inputs remain pending")
    score.add_argument("dataset", type=Path)
    score.add_argument("--annotator", action="append", type=Path, default=[])
    score.add_argument("--adjudication", type=Path)
    score.add_argument("--usage-log", action="append", type=Path, default=[])
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--require-complete", action="store_true")
    recorded = commands.add_parser("import-predictions", help="Import frozen actual observations without overwriting saved predictions")
    recorded.add_argument("dataset", type=Path)
    recorded.add_argument("records", type=Path)
    recorded.add_argument("--output", type=Path, required=True)
    preflight = commands.add_parser("preflight", help="Check real-service prerequisites without invoking a model")
    preflight.add_argument("--api-url", default="http://127.0.0.1:8000")
    preflight.add_argument("--output", type=Path, required=True)
    collect = commands.add_parser("collect-grading", help="Run the actual grader once and reuse first-round grades for both variants")
    collect.add_argument("dataset", type=Path)
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            from evaluation.live import preflight_report
            result = preflight_report(args.api_url)
            write_json(args.output, result)
            print(json.dumps({"status": result["status"], "output": str(args.output)}))
            return 0
        data = read_json(args.dataset)
        validate_dataset(data)
        if args.command == "validate":
            print(json.dumps({"valid": True, "dataset_sha256": digest(data),
                              "counts": {kind: sum(item["kind"] == kind for item in data["items"]) for kind in TARGET_COUNTS}}))
        elif args.command == "labels":
            template, workitems = prepare_labels(data)
            for name in ("annotator-a.json", "annotator-b.json"):
                require(not (args.output_dir / name).exists(), f"Refusing to overwrite {name}")
            for name in ("annotator-a.json", "annotator-b.json"):
                write_json(args.output_dir / name, template)
            write_json(args.output_dir / "blind-workitems.json", workitems)
            print(json.dumps({"status": "awaiting_independent_human_labels", "output_dir": str(args.output_dir)}))
        elif args.command == "adjudication":
            template, differences = adjudication_template(data, [read_json(path) for path in args.annotator])
            require(not (args.output_dir / "adjudication.json").exists(), "Refusing to overwrite existing adjudication")
            write_json(args.output_dir / "adjudication.json", template)
            write_json(args.output_dir / "disagreements.json", differences)
            print(json.dumps({"disagreements": len(differences), "output_dir": str(args.output_dir)}))
        elif args.command == "score":
            usage = []
            for path in args.usage_log:
                usage.extend(json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip())
            result = evaluate(data, [read_json(path) for path in args.annotator],
                              read_json(args.adjudication) if args.adjudication else None, usage)
            write_json(args.output, result)
            print(json.dumps({"status": result["status"], "official_accepted": result["official_accepted"], "output": str(args.output)}))
            if args.require_complete:
                return 2 if result["status"] != "complete" else 0 if result["official_accepted"] else 3
        elif args.command == "import-predictions":
            require(args.output.resolve() != args.dataset.resolve(), "Save collected observations as a new dataset snapshot")
            write_json(args.output, import_predictions(data, read_json(args.records)))
            print(json.dumps({"output": str(args.output)}))
        elif args.command == "collect-grading":
            from evaluation.live import collect_grading
            require(args.output.resolve() != args.dataset.resolve(), "Save observations as a new dataset snapshot")
            write_json(args.output, collect_grading(data))
            print(json.dumps({"status": "actual_grading_collected_human_labels_still_required", "output": str(args.output)}))
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        # Do not print provider exceptions, request headers, cookies or secret values.
        print(f"Evaluation command failed ({type(error).__name__}). Check input paths/schema and configured prerequisites.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
