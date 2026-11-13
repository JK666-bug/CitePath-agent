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
    preparation = commands.add_parser("prepare-collection", help="Write empty evidence/workflow bindings without credentials or service calls")
    preparation.add_argument("dataset", type=Path)
    preparation.add_argument("--manifest", type=Path, required=True)
    preparation.add_argument("--output-dir", type=Path, required=True)
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
    merged = commands.add_parser("merge-collections", help="Combine grading, QA and workflow observations from the same original snapshot")
    merged.add_argument("dataset", type=Path)
    merged.add_argument("--collection", type=Path, action="append", required=True)
    merged.add_argument("--output", type=Path, required=True)
    preflight = commands.add_parser("preflight", help="Check real-service prerequisites without invoking a model")
    preflight.add_argument("--api-url", default="http://127.0.0.1:8000")
    preflight.add_argument("--output", type=Path, required=True)
    local_models = commands.add_parser("local-model-smoke", help="Explicitly run bounded local development PDF/embedding/reranker models without SQL or LLM")
    local_models.add_argument("--components", nargs="+", choices=("pdf", "retrieval"), default=["pdf", "retrieval"])
    local_models.add_argument("--corpus", type=Path)
    local_models.add_argument("--output", type=Path, required=True)
    local_models.add_argument("--run", action="store_true")
    collect = commands.add_parser("collect-grading", help="Run the actual grader once and reuse first-round grades for both variants")
    collect.add_argument("dataset", type=Path)
    collect.add_argument("--manifest", type=Path, help="Exact frozen manifest; required with --run")
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--run", action="store_true", help="Explicitly attest the local runtime and invoke the actual grader")
    evidence = commands.add_parser("collect-evidence", help="Collect resumable production QA outputs on explicitly mapped dedicated courses")
    evidence.add_argument("dataset", type=Path)
    evidence.add_argument("--config", type=Path, required=True)
    evidence.add_argument("--checkpoint-dir", type=Path)
    evidence.add_argument("--output", type=Path, required=True)
    evidence.add_argument("--run", action="store_true", help="Explicitly invoke the configured production QA service")
    workflow = commands.add_parser("collect-workflows", help="Collect paired real-session workflow traces; missing adapters remain pending")
    workflow.add_argument("dataset", type=Path)
    workflow.add_argument("--bindings", type=Path, required=True)
    workflow.add_argument("--answers", type=Path, required=True)
    workflow.add_argument("--checkpoint-dir", type=Path, required=True)
    workflow.add_argument("--output", type=Path, required=True)
    workflow.add_argument("--run", action="store_true", help="Explicitly create isolated evaluation sessions")
    integration = commands.add_parser("live-integration", help="Observe a bounded live development API workflow, separate from formal evaluation")
    integration.add_argument("--api-url", default="http://127.0.0.1:8000")
    integration.add_argument("--corpus", type=Path)
    integration.add_argument("--answers", type=Path)
    integration.add_argument("--output", type=Path, required=True)
    integration.add_argument("--allow-create-test-data", action="store_true")
    integration.add_argument("--manage-api-process", action="store_true")
    integration.add_argument("--include-new-materials", action="store_true")
    integration.add_argument("--max-answers", type=int, default=64)
    args = parser.parse_args(argv)
    try:
        if args.command == "local-model-smoke":
            from evaluation.local_models import smoke_local_models
            result = smoke_local_models(run=args.run, components=args.components, corpus_path=args.corpus)
            write_json(args.output, result)
            print(json.dumps({"status": result["status"], "llm_invoked": False, "output": str(args.output)}))
            return 0 if result["status"] == "passed" else 2 if result["status"] == "not_run" else 1
        if args.command == "live-integration":
            from evaluation.integration import run_integration
            try:
                answers = read_json(args.answers) if args.answers else None
                require(answers is None or isinstance(answers, dict), "Answer fixtures must be an object")
                result = run_integration(args.api_url, allow_create=args.allow_create_test_data,
                                         corpus_path=args.corpus, answers=answers,
                                         include_new_materials=args.include_new_materials,
                                         manage_api_process=args.manage_api_process,
                                         max_answers=args.max_answers)
            except (ValueError, OSError) as error:
                result = {"schema": "citepath-live-integration-v1", "status": "failed", "mode": "live_http",
                          "synthetic": False, "formal_evaluation_run": False, "official_accepted": None,
                          "mutation_requests_sent": False, "mutations_performed": False,
                          "failure": {"type": type(error).__name__, "code": "invalid_integration_input"}}
            write_json(args.output, result)
            print(json.dumps({"status": result["status"], "formal_evaluation_run": False, "output": str(args.output)}))
            return 0 if result["status"] == "completed" else 2 if result["status"] in {"blocked", "not_run"} else 1
        if args.command == "preflight":
            from evaluation.live import preflight_report
            result = preflight_report(args.api_url)
            write_json(args.output, result)
            print(json.dumps({"status": result["status"], "output": str(args.output)}))
            return 0
        data = read_json(args.dataset)
        validate_dataset(data)
        if args.command == "prepare-collection":
            from evaluation.preparation import collection_templates
            templates = collection_templates(data, args.manifest.resolve())
            require(not args.output_dir.exists(), "Use a new directory for empty collection bindings")
            protected = Path(__file__).resolve().parents[2] / "evaluation_assets"
            require(args.output_dir.resolve() != protected and protected not in args.output_dir.resolve().parents,
                    "Keep runtime configuration outside distributed evaluation assets")
            for filename, value in templates.items():
                write_json(args.output_dir / filename, value)
            print(json.dumps({"status": "awaiting_runtime_bindings", "model_invoked": False, "output": str(args.output_dir)}))
            return 0
        if args.command in {"collect-evidence", "collect-workflows"}:
            require(args.output.resolve() != args.dataset.resolve(), "Save collection results outside the input dataset")
            input_paths = [args.dataset, *([args.config] if args.command == "collect-evidence" else [args.bindings, args.answers])]
            require(args.output.resolve() not in {path.resolve() for path in input_paths}, "Collection output cannot replace configuration or input files")
            protected = Path(__file__).resolve().parents[2] / "evaluation_assets"
            require(args.output.resolve() != protected and protected not in args.output.resolve().parents,
                    "Save actual results outside distributed preparation cohorts")
            if args.command == "collect-evidence":
                from evaluation.evidence import collect_evidence
                result = collect_evidence(data, read_json(args.config), run=args.run, checkpoint_dir=args.checkpoint_dir)
                report_path = args.output.with_suffix(args.output.suffix + ".report.json")
                journal_path = args.output.with_suffix(args.output.suffix + ".journal.json")
                require(report_path.resolve() != args.dataset.resolve() and journal_path.resolve() != args.dataset.resolve(), "Output paths collide with input")
                write_json(args.output, result["dataset"])
                write_json(report_path, result["report"])
                write_json(journal_path, result["journal"])
                status = result["report"]["status"]
            else:
                from evaluation.workflows import collect_workflows
                try:
                    result = collect_workflows(data, bindings=read_json(args.bindings), answers=read_json(args.answers),
                                               checkpoint_dir=args.checkpoint_dir, allow_create_sessions=args.run)
                except (ValueError, RuntimeError, OSError, ImportError) as error:
                    result = {"schema": "citepath-workflow-collection-v1", "dataset_sha256": digest(data),
                              "status": "blocked", "synthetic": False, "records": [], "run_statuses": [],
                              "official_accepted": None, "failure_type": type(error).__name__}
                write_json(args.output, result)
                status = result["status"]
            print(json.dumps({"status": status, "official_accepted": None, "output": str(args.output)}))
            return 0 if status == "completed" else 1 if status == "failed" else 2
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
        elif args.command == "merge-collections":
            from evaluation.merge import merge_collections
            require(args.output.resolve() not in {path.resolve() for path in [args.dataset, *args.collection]}, "Save merged observations as a new snapshot")
            write_json(args.output, merge_collections(data, [read_json(path) for path in args.collection]))
            print(json.dumps({"status": "merged_observations_human_labels_still_required", "output": str(args.output)}))
        elif args.command == "collect-grading":
            from evaluation.live import collect_grading
            require(args.output.resolve() != args.dataset.resolve(), "Save observations as a new dataset snapshot")
            require(args.manifest is None or args.output.resolve() != args.manifest.resolve(), "Collection output cannot replace the frozen manifest")
            protected = Path(__file__).resolve().parents[2] / "evaluation_assets"
            require(args.output.resolve() != protected and protected not in args.output.resolve().parents,
                    "Save actual results outside distributed preparation cohorts")
            require(not args.output.exists(), "Use a new grading output file; saved observations cannot be overwritten")
            write_json(args.output, collect_grading(data, manifest_path=args.manifest, run=args.run))
            status = "actual_grading_collected_human_labels_still_required" if args.run else "not_run"
            print(json.dumps({"status": status, "model_invoked": args.run, "output": str(args.output)}))
            if not args.run:
                return 2
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        # Do not print provider exceptions, request headers, cookies or secret values.
        print(f"Evaluation command failed ({type(error).__name__}). Check input paths/schema and configured prerequisites.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
