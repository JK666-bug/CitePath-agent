"""Assemble the acceptance evidence summary from saved probe outputs."""
import json
import re
import sys
from pathlib import Path

EV = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1
      else Path(__file__).resolve().parents[2] / "evidence")


def read(name):
    return (EV / name).read_text(encoding="utf-8-sig", errors="replace")


def main():
    summary = {"date": "2026-11-13", "code_dir": str(EV.parent)}
    backend = read("backend-tests-284.txt")
    match = re.search(r"Ran (\d+) tests in ([\d.]+)s", backend)
    summary["backend_tests"] = {
        "tests": int(match.group(1)) if match else None,
        "seconds": float(match.group(2)) if match else None,
        "ok": any(line.strip() == "OK" for line in backend.splitlines()),
    }
    summary["frontend_build"] = {"built": "built in" in read("frontend-build.txt")}
    lint = read("frontend-lint.txt")
    match = re.search(r"Found (\d+) warnings and (\d+) errors", lint)
    summary["frontend_lint"] = {
        "warnings": int(match.group(1)) if match else None,
        "errors": int(match.group(2)) if match else None,
    }
    suites = {}
    for name in ("practice", "feedback", "upstream", "planning", "restoration"):
        data = json.loads(read(f"ui-{name}-ui-smoke.txt"))
        suites[name] = len(data.get("checks") or [])
    summary["mocked_ui_checks"] = {
        "per_suite": suites,
        "total": sum(suites.values()),
    }
    live = json.loads(read("live-ui-acceptance.json"))
    summary["live_ui"] = {
        "status": live.get("status"),
        "checks": len(live.get("checks") or []),
        "passed": sum(1 for check in live.get("checks") or [] if check.get("passed")),
        "mutations": live.get("mutations_performed"),
    }
    summary["mysql"] = json.loads(read("mysql-probe.json"))
    summary["milvus"] = json.loads(read("milvus-probe.json"))
    summary["api"] = json.loads(read("api-probe.json"))
    summary["live_practice"] = json.loads(read("live-practice-acceptance.json"))
    summary["duplicate"] = json.loads(read("duplicate-probe.json"))
    summary["session5"] = json.loads(read("session-5-probe.json"))
    prior = json.loads(read("prior-live-integration-v8.json"))
    summary["prior_live_integration"] = {
        "checks": len(prior.get("checks") or []),
        "passed": sum(1 for check in prior.get("checks") or [] if check.get("status") == "passed"),
        "status": prior.get("status"),
    }
    (EV / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "backend_tests", "frontend_build", "frontend_lint", "mocked_ui_checks",
        "live_ui", "prior_live_integration")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
