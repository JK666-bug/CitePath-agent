"""Run reproducible synthetic baseline/agent comparisons on MySQL TEMPORARY tables.

From backend: .venv/bin/python -B tools/evaluate_planner.py --live --output docs/planner-evaluation.json
Only --live calls the configured model. No real course contents are sent.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["CITEPATH_SYNC_MYSQL_TESTS"] = "1"

from test_scheduling_mysql import SchedulingMySQLTest, ObservingModel
from agent.planner import run_planner
from agent.llm import chat_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    records = []
    SchedulingMySQLTest.setUpClass()
    try:
        for scenario in ("feasible", "insufficient_capacity", "weak_chapter", "completed_read"):
            for mode in ("baseline", "agent"):
                fixture = SchedulingMySQLTest("test_agent_chooses_tools_and_publishes_once")
                fixture.setUp()
                profile = dict(fixture.profile)
                if scenario == "insufficient_capacity":
                    profile.update(end=profile["start"], daily_minutes=1)
                if scenario == "completed_read":
                    from db.plans import complete_read_task
                    complete_read_task(10, 1, "reading-4")
                if scenario == "weak_chapter":
                    fixture.finish_exam(fixture.start_exam(), False)
                before = fixture.stored()
                model = chat_model().bind(timeout=25, max_retries=0) if args.live else ObservingModel()
                result = run_planner(10, 1, f"{scenario}-{mode}", profile, mode=mode, model=model)
                after = fixture.stored()
                same_tasks = {t["id"] for t in before["tasks"]} == {t["id"] for t in after["tasks"]}
                completed_preserved = all(t == next(x for x in after["tasks"] if x["id"] == t["id"])
                                          for t in before["tasks"] if t["status"] == "Completed")
                records.append({"scenario": scenario, "mode": mode, "status": result["status"],
                                "duration_ms": result["duration_ms"], "task_identity_preserved": same_tasks,
                                "completed_tasks_preserved": completed_preserved,
                                "tools": [s["tool"] for s in result["trace"]], "trace": result["trace"]})
                print(scenario, mode, result["status"], result["duration_ms"], "ms", flush=True)
    finally:
        SchedulingMySQLTest.doClassCleanups()
    payload = {"at": datetime.now(timezone.utc).isoformat(),
               "model_mode": "live" if args.live else "test_double",
               "scope": "Synthetic one-chapter fixtures on connection-local temporary tables; not a formal learning-quality evaluation.",
               "records": records}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
