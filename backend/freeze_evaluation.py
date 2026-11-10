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


def manifest():
    settings = {**dotenv_values(ROOT / ".env"), **os.environ}
    constants = {}
    hashes = {}
    for name in FILES:
        data = (ROOT / name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        if name.endswith(".py"):
            public = {}
            for node in ast.parse(data).body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper() and not target.id.endswith("SYSTEM"):
                            try:
                                public[target.id] = ast.literal_eval(node.value)
                            except (ValueError, TypeError):
                                pass
            constants[name] = public
    packages = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit, "working_tree_dirty": dirty,
        "python": platform.python_version(), "platform": platform.platform(),
        "deployment": settings.get("HKU_DEPLOYMENT") or constants["agent/llm.py"]["DEFAULT_DEPLOYMENT"],
        "api_version": settings.get("HKU_API_VERSION") or constants["agent/llm.py"]["DEFAULT_API_VERSION"],
        "model_temperature": 0, "model_timeout_seconds": 60, "model_max_retries": 1,
        "source_sha256": hashes, "constants": constants, "installed_packages": packages,
        "development_lectures": [2, 3], "held_out_lectures": [4, 6, 8],
        "evaluation_status": "not_run",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved evaluation configuration: {arguments.output}")
