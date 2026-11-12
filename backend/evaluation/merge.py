"""Merge complementary actual collections against their unchanged original input."""
import copy
from evaluation.core import VARIANTS, digest, require, validate_dataset


def inputs_only(data):
    result = copy.deepcopy(data)
    for item in result["items"]:
        item["predictions"] = {variant: None for variant in VARIANTS}
    return result


def merge_collections(original, collections):
    validate_dataset(original)
    require(all(value is None for item in original["items"] for value in (item.get("predictions") or {}).values()),
            "Merge against the original unobserved input snapshot")
    require(isinstance(collections, list) and collections, "Provide actual collection files")
    items = {item["id"]: item for item in original["items"]}
    records = {}
    for collected in collections:
        require(isinstance(collected, dict), "Invalid collection document")
        require(collected.get("synthetic") is not True or original["synthetic"], "Synthetic collections cannot enter a real evaluation cohort")
        if collected.get("schema") == original["schema"]:
            validate_dataset(collected)
            require(digest(inputs_only(collected)) == digest(inputs_only(original)), "Collection rewrote frozen questions, materials, policy or configuration")
            incoming = [{"item_id": item["id"], "variant": variant, "prediction": prediction}
                        for item in collected["items"] for variant, prediction in (item.get("predictions") or {}).items()
                        if prediction is not None]
        else:
            require(collected.get("dataset_sha256") == digest(original), "Collection belongs to a different original input")
            require(not collected.get("controller_records"), "Controller observations require a separate synthetic cohort")
            incoming = collected.get("records")
            require(isinstance(incoming, list), "Collection records are missing")
        for record in incoming:
            key = (record.get("item_id"), record.get("variant"))
            require(key[0] in items and key[1] in VARIANTS and isinstance(record.get("prediction"), dict), "Unknown collected prediction")
            if key in records:
                require(records[key]["prediction"] == record["prediction"], "Conflicting actual observations cannot overwrite one another")
            records[key] = copy.deepcopy(record)
    from evaluation.__main__ import import_predictions
    return import_predictions(original, {"dataset_sha256": digest(original), "records": list(records.values())})
