"""Build the 20 scenarios x 3 repeats x 2 systems = 120-run formal batch sheet.

The sheet is derived only from the frozen dataset and empty workflow bindings.
It does not create accounts, call models, or invent observations.
"""
import argparse
import csv
import json
from pathlib import Path


def build(dataset, bindings):
    cases = bindings.get("cases") or {}
    rows = []
    for item in dataset["items"]:
        if item.get("kind") != "workflow":
            continue
        scenario = item.get("scenario") or {}
        item_id = item["id"]
        repeats = int(scenario.get("repeats_per_system") or 3)
        if repeats != 3:
            raise ValueError(f"{item_id}: expected 3 repeats, found {repeats}")
        for repeat in range(1, repeats + 1):
            fixtures = (cases.get(item_id) or {}).get(str(repeat)) or {}
            for variant in ("baseline", "full"):
                fixture = fixtures.get(variant) or {}
                shared = fixtures.get("shared") or {}
                rows.append({
                    "run_id": f"{item_id}-{variant}-r{repeat}",
                    "item_id": item_id,
                    "scenario": scenario.get("name"),
                    "variant": variant,
                    "repeat": repeat,
                    "passing_threshold": scenario.get("passing_threshold"),
                    "required_branch": scenario.get("required_branch"),
                    "planned_followup_input": scenario.get("planned_followup_input"),
                    "policy": (item.get("expected") or {}).get(variant, {}).get("policy"),
                    "lecture": item.get("lecture"),
                    "question": item.get("question"),
                    "shared_fixture_present": bool(shared),
                    "variant_username_env": fixture.get("username_env"),
                    "variant_password_env": fixture.get("password_env"),
                    "shared_username_env": shared.get("username_env"),
                    "shared_password_env": shared.get("password_env"),
                    "observation_status": "not_run",
                })
    if len(rows) != 120:
        raise ValueError(f"Expected 120 runs, built {len(rows)}")
    return {
        "schema": "citepath-formal-run-batch-v1",
        "dataset_sha256": bindings.get("dataset_sha256"),
        "configuration_sha256": bindings.get("configuration_sha256"),
        "scenarios": len(rows) // 6,
        "variants": 2,
        "repeats_per_system": 3,
        "runs": len(rows),
        "official_accepted": None,
        "runs_status": "not_run",
        "records": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("bindings")
    parser.add_argument("--json", required=True)
    parser.add_argument("--csv", required=True)
    args = parser.parse_args()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8-sig"))
    bindings = json.loads(Path(args.bindings).read_text(encoding="utf-8-sig"))
    result = build(dataset, bindings)
    Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with Path(args.csv).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["records"][0]))
        writer.writeheader()
        writer.writerows(result["records"])
    print(json.dumps({key: result[key] for key in (
        "scenarios", "variants", "repeats_per_system", "runs", "runs_status")}))


if __name__ == "__main__":
    main()
