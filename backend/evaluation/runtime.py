"""Compare frozen configuration with observed code without exporting credentials."""
import hashlib
import json
from pathlib import Path

from evaluation.core import digest, require, timestamp, validate_dataset


def runtime_summary():
    from freeze_evaluation import manifest
    value = manifest()
    return {"schema": "citepath-evaluation-runtime-v1", "provider": value["provider"],
            "model": value["model"], "api_version": value["api_version"],
            "base_url_sha256": value["base_url_sha256"], "source_sha256": value["source_sha256"],
            "git_commit": value["git_commit"], "python": value["python"],
            "runtime_packages_sha256": digest(value["installed_packages"]),
            "model_cost_configuration": value.get("model_cost_configuration"),
            "retrieval_configuration": value.get("retrieval_configuration"),
            "qa_policy": "production_qa_shared_v1"}


def load_frozen_manifest(data, manifest_path):
    validate_dataset(data)
    require(isinstance(manifest_path, (str, Path)) and str(manifest_path), "A frozen manifest path is required")
    try:
        raw = Path(manifest_path).read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("The frozen manifest cannot be read") from None
    freeze = data.get("freeze") or {}
    from datetime import datetime, timezone
    require(timestamp(freeze.get("created_at")) <= datetime.now(timezone.utc), "Frozen timestamp is in the future")
    require(hashlib.sha256(raw).hexdigest() == freeze.get("manifest_sha256"), "Frozen manifest identity differs")
    require(isinstance(value, dict) and value.get("working_tree_dirty") is False, "Freeze committed clean source before collection")
    require(value.get("git_commit") == freeze.get("git_commit"), "Frozen commit differs")
    require(value.get("created_at") == freeze.get("created_at"), "Frozen timestamp differs")
    for field in ("provider", "model", "base_url_sha256"):
        require(bool(value.get(field)) and value[field] == freeze.get(field), "Frozen model configuration differs")
    require(isinstance(value.get("source_sha256"), dict) and value["source_sha256"], "Frozen source hashes are required")
    require(isinstance(value.get("installed_packages"), dict) and value["installed_packages"], "Frozen package versions are required")
    return value


def verify_observed_runtime(data, manifest, observed):
    require(isinstance(observed, dict) and observed.get("schema") == "citepath-evaluation-runtime-v1", "Unknown runtime configuration schema")
    for field in ("provider", "model", "api_version", "base_url_sha256", "source_sha256", "python", "model_cost_configuration", "retrieval_configuration"):
        require(observed.get(field) == manifest.get(field), "Running service differs from frozen configuration")
    packages = digest(manifest["installed_packages"])
    require(observed.get("runtime_packages_sha256") == packages, "Running package versions differ from frozen environment")
    return {"provider": observed["provider"], "model": observed["model"],
            "base_url_sha256": observed["base_url_sha256"], "source_sha256": observed["source_sha256"],
            "configuration_sha256": data["freeze"]["manifest_sha256"],
            "runtime_packages_sha256": packages, "git_commit": observed.get("git_commit")}


def verify_runtime(data, bindings):
    require(isinstance(bindings, dict), "Runtime bindings must be an object")
    require(bindings.get("dataset_sha256") == digest(data), "Runtime bindings belong to another dataset")
    require(bindings.get("configuration_sha256") == (data.get("freeze") or {}).get("manifest_sha256"),
            "Runtime bindings belong to another configuration")
    manifest = load_frozen_manifest(data, bindings.get("manifest_path"))
    from agent.llm import model_configuration
    require(model_configuration()["key_configured"], "The selected model key is not configured")
    return verify_observed_runtime(data, manifest, runtime_summary())
