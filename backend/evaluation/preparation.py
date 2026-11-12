"""Prepare empty runtime bindings without inventing accounts, IDs or observations."""
from evaluation.core import VARIANTS, digest, validate_dataset


def collection_templates(data, manifest_path):
    validate_dataset(data)
    freeze = data.get("freeze") or {}
    evidence = {"schema": "citepath-evidence-runtime-v1", "manifest_path": str(manifest_path),
                "qa_policy": "production_qa_shared_v1", "variants": {}}
    for variant in VARIANTS:
        evidence["variants"][variant] = {"api_url": "http://127.0.0.1:8000", "course_id": None,
            "username_env": f"CITEPATH_EVIDENCE_{variant.upper()}_USER", "password_env": f"CITEPATH_EVIDENCE_{variant.upper()}_PASSWORD",
            "documents": [{"frozen_document_id": document["id"], "runtime_document_id": None,
                           "sha256": document["sha256"], "page_count": document["page_count"]}
                          for document in data["documents"]]}
    workflows = {"dataset_sha256": digest(data), "configuration_sha256": freeze.get("manifest_sha256"),
                 "manifest_path": str(manifest_path), "owned_api_url": "http://127.0.0.1:8011", "cases": {}}
    for number, item in enumerate((item for item in data["items"] if item["kind"] == "workflow"), 1):
        workflows["cases"][item["id"]] = {}
        for repeat in (1, 2, 3):
            workflows["cases"][item["id"]][str(repeat)] = {
                role: {"user_id": None, "course_id": None, "chapter_id": None,
                       "username_env": f"CITEPATH_WF_{number:02}_R{repeat}_{role.upper()}_USER",
                       "password_env": f"CITEPATH_WF_{number:02}_R{repeat}_{role.upper()}_PASSWORD"}
                for role in ("shared", *VARIANTS)}
    answers = {"mcq": "A", "short": "I am not confident about this concept yet.",
               "qa_question": "According to the uploaded lecture, what is the purpose of the main data structure?"}
    answers["by_scenario"] = {}
    for item in data["items"]:
        if item["kind"] != "workflow" or "required_branch" not in (item.get("scenario") or {}):
            continue
        scenario = item["scenario"]
        answers["by_scenario"][item["id"]] = {
            "round1": {"policy": "reference" if scenario["required_branch"] == "first_round_pass" else "wrong_reference"},
            "round2": {"policy": "reference" if scenario.get("planned_followup_input") == "reference" else "wrong_reference"},
            "qa_question": answers["qa_question"]}
    return {"evidence-runtime.template.json": evidence, "workflow-bindings.template.json": workflows,
            "development-response-policy.template.json": answers,
            "preparation-status.json": {"dataset_sha256": digest(data), "runtime_ids_observed": False,
                "credentials_present": False, "response_policy": "authored_deterministic_inputs_not_student_data",
                "human_review_completed": False, "official_accepted": None}}
