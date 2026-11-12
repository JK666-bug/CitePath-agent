"""Real prerequisite checks and explicitly invoked grading collection, never mocks."""
import copy
import json
import os
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from evaluation.core import VARIANTS, require, validate_dataset


RUNTIME_MODULES = {"pymysql": "pymysql", "pymilvus": "pymilvus", "fitz": "fitz",
                   "docling": "docling.document_converter", "fastembed": "fastembed", "llm": "agent.llm",
                   "mysql_rsa": "cryptography.hazmat.primitives.asymmetric.rsa"}


def runtime_imports(timeout=30):
    """Import native dependencies in a bounded child, without constructing models.

    A package can be discoverable yet unusable because one of its DLLs cannot
    load. Only fixed module names and booleans cross back into the report.
    """
    script = """import contextlib, importlib, json, os, sys
modules = json.loads(sys.argv[1])
for label, module in modules.items():
    ready = False
    with open(os.devnull, 'w') as sink:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            try:
                importlib.import_module(module)
                ready = True
            except BaseException:
                pass
    print(json.dumps([label, ready]), flush=True)
"""
    results = {name: False for name in RUNTIME_MODULES}
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, json.dumps(RUNTIME_MODULES)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output, status = completed.stdout, "completed" if completed.returncode == 0 else "process_failed"
    except subprocess.TimeoutExpired as error:
        output, status = error.stdout or "", "timeout"
    except OSError:
        return results, "unavailable"
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    for line in output.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (isinstance(record, list) and len(record) == 2
                and isinstance(record[0], str) and record[0] in results and type(record[1]) is bool):
            results[record[0]] = record[1]
    # A native crash or timeout cannot establish complete runtime readiness.
    if status != "completed" and all(results.values()):
        results = dict.fromkeys(results, False)
    return results, status


class _NoHealthRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise OSError("health_redirect_refused")


def api_health(api_url):
    """Probe only a loopback origin; redirects and proxy settings are ignored."""
    try:
        parsed = urllib.parse.urlsplit(api_url)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            return False
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoHealthRedirects())
        with opener.open(api_url.rstrip("/") + "/api/health", timeout=2) as response:
            result = json.loads(response.read(4096).decode("utf-8"))
            return response.status == 200 and isinstance(result, dict) and result.get("status") == "ok"
    except (OSError, ValueError, UnicodeError):
        return False


def preflight_report(api_url="http://127.0.0.1:8000"):
    from dotenv import dotenv_values
    root = Path(__file__).resolve().parents[1]
    settings = {**dotenv_values(root / ".env"), **os.environ}
    checks = []

    def check(name, ready, detail):
        checks.append({"name": name, "ready": bool(ready), "detail": detail})

    try:
        from agent.llm import model_configuration
        model = model_configuration(settings)
        ready = model["key_configured"]
        detail = (f"A runner-local key is configured for the selected {model['provider']} provider; authentication and the running API configuration are not verified"
                  if ready else f"Set {model['key_name']} locally in backend/.env for the selected {model['provider']} provider; never put it in labels or logs")
        check("model_configuration", ready, detail)
    except RuntimeError as error:
        model = None
        check("model_configuration", False, str(error))
    except (ImportError, OSError):
        model = None
        check("model_configuration", False, "The model runtime cannot import; repair the pinned runtime dependencies before configuration checks")
    imported, import_status = runtime_imports()
    missing = [name for name, ready in imported.items() if not ready]
    check("full_runtime_dependencies", not missing and import_status == "completed",
          "Full runtime imports succeeded without constructing a model" if not missing and import_status == "completed"
          else "Runtime import check " + import_status + "; unavailable modules: " + ", ".join(missing))
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
    healthy = api_health(api_url)
    check("api_health", healthy, "API health responds; no inference was requested" if healthy else "Start the configured FastAPI service before running live workflows")
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "prerequisites_available" if all(row["ready"] for row in checks) else "blocked",
            "checks": checks, "model_invoked": False, "formal_evaluation_run": False,
            "model_configuration": model, "model_configuration_scope": "runner_local",
            "server_model_configuration_verified": False,
            "runtime_imports": imported, "runtime_import_status": import_status,
            "limits": ["A listening port does not establish database authentication or persistence correctness.",
                       "Model settings describe this runner; an already running API may use a different configuration, which is not verified by health.",
                       "Successful imports do not establish availability of PDF conversion or embedding model artifacts.",
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
