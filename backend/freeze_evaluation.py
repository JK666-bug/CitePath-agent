"""Record reproducible configuration without making a model call or saving keys."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
FILES = ["agent/llm.py", "agent/exam.py", "agent/practice.py", "agent/plan.py",
         "agent/qa.py", "agent/skills/qa/SKILL.md", "grading/score.py",
         "vector/segments.py", "vector/rerank.py", "requirements.txt"]
FILES = sorted(set(FILES) | {
    str(path.relative_to(ROOT)).replace("\\", "/")
    for folder in ("agent", "db", "grading", "ingest", "vector", "evaluation")
    for path in (ROOT / folder).rglob("*.py")
} | {"main.py", "db/schema.sql", "freeze_evaluation.py", "requirements-test.txt", "requirements-windows.txt"})


def configuration_value(value):
    if isinstance(value, dict):
        return {str(key): configuration_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [configuration_value(item) for item in sorted(value, key=repr)]
    if isinstance(value, (tuple, list)):
        return [configuration_value(item) for item in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("Not a JSON configuration literal")


def manifest():
    settings = {**dotenv_values(ROOT / ".env"), **os.environ}
    from agent.llm import model_configuration
    model = model_configuration(settings)
    from vector.segments import COLLECTION
    retrieval = {"collection": COLLECTION,
                 "milvus_uri_sha256": hashlib.sha256(
                     os.environ.get("MILVUS_URI", "http://127.0.0.1:19530").encode()).hexdigest()}
    from agent.telemetry import _rate
    constants = {}
    hashes = {}
    for name in FILES:
        data = (ROOT / name).read_bytes()
        hashes[name] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
        if name.endswith(".py"):
            public = {}
            for node in ast.parse(data).body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper() and not target.id.endswith("SYSTEM"):
                            try:
                                public[target.id] = configuration_value(ast.literal_eval(node.value))
                            except (ValueError, TypeError):
                                pass
            constants[name] = public
    # An overlay environment can expose more than one distribution of a name.
    # Record the version selected by the interpreter, rather than the last one
    # encountered on a later sys.path entry.
    packages = {dist.metadata["Name"]: importlib.metadata.version(dist.metadata["Name"])
                for dist in importlib.metadata.distributions()}
    try:
        git = ["git", "-c", f"safe.directory={ROOT.parent.as_posix()}"]
        commit = subprocess.check_output([*git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output([*git, "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit, "working_tree_dirty": dirty,
        "python": platform.python_version(), "platform": platform.platform(),
        "provider": model["provider"], "model": model["model"],
        "deployment": model["model"], "api_version": model["api_version"],
        "base_url_sha256": model["base_url_sha256"],
        "retrieval_configuration": retrieval,
        "model_key_name": model["key_name"], "model_key_configured": model["key_configured"],
        "model_temperature": 0, "model_timeout_seconds": model["timeout"], "model_max_retries": 1,
        "model_cost_configuration": {"input_per_million": _rate("MODEL_INPUT_COST_PER_MILLION"),
                                     "output_per_million": _rate("MODEL_OUTPUT_COST_PER_MILLION"),
                                     "currency": settings.get("MODEL_COST_CURRENCY") or None},
        "source_sha256": hashes, "source_hash_encoding": "UTF-8 source bytes with CRLF normalized to LF",
        "constants": constants, "installed_packages": packages,
        "development_lectures": [2, 3], "held_out_lectures": [4, 6, 8],
        "evaluation_status": "not_run",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Saved evaluation configuration: {arguments.output}")
