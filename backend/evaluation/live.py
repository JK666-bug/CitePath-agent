"""Real prerequisite checks and explicitly invoked grading collection, never mocks."""
import copy
import importlib.util
import os
import socket
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from evaluation.core import VARIANTS, require, validate_dataset


def preflight_report(api_url="http://127.0.0.1:8000"):
    from dotenv import dotenv_values
    from agent.llm import model_configuration
    root = Path(__file__).resolve().parents[1]
    settings = {**dotenv_values(root / ".env"), **os.environ}
    checks = []

    def check(name, ready, detail):
        checks.append({"name": name, "ready": bool(ready), "detail": detail})

    try:
        model = model_configuration(settings)
        ready = model["key_configured"]
        detail = (f"A key is configured for the selected {model['provider']} provider; authentication is not yet verified"
                  if ready else f"Set {model['key_name']} locally in backend/.env for the selected {model['provider']} provider; never put it in labels or logs")
        check("model_configuration", ready, detail)
    except RuntimeError as error:
        model = None
        check("model_configuration", False, str(error))
    missing = [name for name in ("pymysql", "pymilvus", "fitz", "docling", "fastembed") if importlib.util.find_spec(name) is None]
    check("full_runtime_dependencies", not missing, "Full runtime installed" if not missing else "Install backend/requirements.txt; missing modules: " + ", ".join(missing))
    for name, host, port in (
        ("mysql", settings.get("MYSQL_HOST") or "127.0.0.1", int(settings.get("MYSQL_PORT") or 3306)),
        ("milvus", "127.0.0.1", 19530),
    ):
        try:
            with socket.create_connection((host, port), timeout=1):
                ready = True
        except OSError:
            ready = False
        check(name + "_listener", ready, "TCP reachable; authentication/schema still require integration verification" if ready else "Required database listener is unavailable; start Docker Compose")
    try:
        with urllib.request.urlopen(api_url.rstrip("/") + "/api/health", timeout=2) as response:
            healthy = response.status == 200
    except (OSError, ValueError):
        healthy = False
    check("api_health", healthy, "API health responds; no inference was requested" if healthy else "Start the configured FastAPI service before running live workflows")
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "prerequisites_available" if all(row["ready"] for row in checks) else "blocked",
            "checks": checks, "model_invoked": False, "formal_evaluation_run": False,
            "model_configuration": model,
            "limits": ["A listening port does not establish database authentication or persistence correctness.",
                       "Human labels and live workflow observations remain separate required evidence."]}


def collect_grading(data):
    """Use real application grading; callers must supply a frozen, audited question bank.

    This does not run retrieval, feedback, persistence, or two-round workflows.
    The shared first round is executed only once for a controlled baseline comparison.
    """
    validate_dataset(data)
    from agent.exam import _grade_shorts
    from agent.llm import chat_model, model_configuration
    from agent.telemetry import usage_context
    from grading.score import choice_correct, points_pass
    # Instantiate (without requesting inference) first so absence of a key never
    # leaves a partially collected bank that could be mistaken for a complete run.
    configuration = model_configuration()
    model = chat_model()
    freeze = data.get("freeze") or {}
    require(all(freeze.get(key) for key in ("manifest_sha256", "created_at", "git_commit", "model")), "Freeze configuration before collecting predictions")
    require(getattr(model, "model_name", None) == freeze["model"], "The configured grader model differs from the frozen model")
    require(configuration["model"] == freeze["model"], "The selected provider model differs from the frozen model")
    require(freeze.get("provider", "hku") == configuration["provider"], "The selected provider differs from the frozen provider")
    if configuration["provider"] != "hku":
        require(bool(freeze.get("base_url_sha256")), "Freeze the selected provider endpoint before collection")
    if freeze.get("base_url_sha256"):
        require(freeze["base_url_sha256"] == configuration["base_url_sha256"], "The selected endpoint differs from the frozen endpoint")
    from evaluation.core import _freeze_problems
    require(not _freeze_problems(data), "Complete and validate frozen metadata before collection")
    for item in data["items"]:
        if item["kind"] in ("mcq", "short"):
            require(all((item.get("predictions") or {}).get(variant) is None for variant in VARIANTS), "Do not overwrite previously collected grades")
        if item["kind"] == "mcq":
            require(item.get("answer_key") in ("A", "B", "C", "D"), "MCQ collection needs an explicitly recorded candidate answer_key; humans must audit it independently")
    updated = copy.deepcopy(data)
    short_items = [(number, item) for number, item in enumerate(updated["items"], 1) if item["kind"] == "short"]
    with usage_context(operation="evaluation.grading", evaluation_id=data["evaluation_id"], system="shared_first_round"):
        matches = _grade_shorts([({"id": number}, item["response"], item["rubric"]) for number, item in short_items])
    hits = {item["id"]: matches[number] for number, item in short_items}
    now = datetime.now(timezone.utc).isoformat()
    for item in updated["items"]:
        if item["kind"] not in ("mcq", "short"):
            continue
        actual_hits = hits[item["id"]] if item["kind"] == "short" else None
        correct = (points_pass(len(actual_hits), len(item["rubric"])) if actual_hits is not None
                   else choice_correct(item["response"], item["answer_key"]))
        prediction = {"correct": correct, "collected_at": now,
                      "configuration_sha256": freeze["manifest_sha256"], "model": freeze["model"],
                      "provider": configuration["provider"], "base_url_sha256": configuration["base_url_sha256"],
                      "collector": "application_grader_shared_first_round", "rubric_hits": actual_hits}
        item["predictions"] = {variant: copy.deepcopy(prediction) for variant in VARIANTS}
    return updated
