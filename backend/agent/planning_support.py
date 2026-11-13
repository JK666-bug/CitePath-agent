"""Transparent planning inputs and workload estimates, without model guesses."""
import copy
import math
import re

PROFILE_QUESTIONS = {
    "goal": "What would you like to achieve in this course?",
    "prior_knowledge": "What do you already know about this course?",
    "daily_minutes": "How many minutes can you study each day?",
}
DEFAULT_PROFILE = {"goal": "Study the uploaded course material", "prior_knowledge": "Not specified",
                   "daily_minutes": 60, "reading_words_per_minute": 180}


def planning_profile(profile=None, note="", saved=None, strict=False):
    if profile is not None and not isinstance(profile, dict):
        raise ValueError("Planning profile must be an object")
    supplied = dict(profile or {})
    if "background" in supplied and "prior_knowledge" not in supplied:
        supplied["prior_knowledge"] = supplied["background"]
    normalized, assumptions, questions = {}, [], []
    for field in ("goal", "prior_knowledge", "daily_minutes", "reading_words_per_minute"):
        value = supplied.get(field)
        missing = value is None or value == ""
        if field in ("goal", "prior_knowledge"):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be text")
            missing = missing or not str(value or "").strip()
        elif not missing:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{field} must be a finite number")
            limit = 1440 if field == "daily_minutes" else 1200
            if not 1 <= value <= limit or (field == "daily_minutes" and int(value) != value):
                raise ValueError(f"{field} must be between 1 and {limit}")
        if missing:
            if strict and field in PROFILE_QUESTIONS:
                questions.append({"id": field, "prompt": PROFILE_QUESTIONS[field], "required": True})
            value = (saved or {}).get(field)
            if value is None or value == "":
                value = note.strip() if field == "goal" and note.strip() else DEFAULT_PROFILE[field]
                assumptions.append(field)
            elif field in ((saved or {}).get("assumptions") or []):
                assumptions.append(field)
        normalized[field] = value.strip()[:2000] if isinstance(value, str) else value
    normalized["daily_minutes"] = int(normalized["daily_minutes"])
    normalized["assumptions"] = assumptions
    return normalized, questions


def page_keys(plan):
    return {(int(source["document_id"]), int(source["page_number"]))
            for chapter in plan.get("chapters") or [] for source in chapter.get("sources") or []}


def material_update(plan, pages, documents):
    known = page_keys(plan) if plan else set()
    pending = [page for page in pages if (int(page["document_id"]), int(page["page_number"])) not in known]
    current_ids = {int(document["id"]) for document in documents}
    known_ids = {key[0] for key in known}
    ready = bool(documents) and all(document.get("ingest_status") == "complete" for document in documents)
    return {"new_page_count": len(pending),
            "new_document_ids": sorted({int(page["document_id"]) for page in pending} - known_ids),
            "missing_document_ids": sorted(known_ids - current_ids),
            "can_update": bool(pending) and ready}


def estimate_plan(plan, pages, profile):
    """Use measured text size plus explicit heuristic study overheads.

    Completed task snapshots are immutable, including any old/missing estimate.
    Token units are Latin/numeric words or individual CJK characters, not tokens
    billed by a provider. Rates and concept overheads are assumptions, not research.
    """
    result = copy.deepcopy(plan)
    bodies = {(int(page["document_id"]), int(page["page_number"])): str(page.get("body") or "") for page in pages}
    pace = float(profile["reading_words_per_minute"])
    chapter_estimates = {}
    for chapter in result["chapters"]:
        keys = {(int(source["document_id"]), int(source["page_number"])) for source in chapter.get("sources") or []}
        units = sum(len(re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", bodies[key])) for key in keys if key in bodies)
        concepts = len(chapter.get("concepts") or [])
        missing = len(keys - set(bodies))
        reading = max(len(keys), math.ceil(units / pace) + 2 * concepts, 1)
        estimates = {"Reading": reading, "Practice": max(6 * concepts, 6), "Review": max(4 * concepts, 4)}
        chapter_estimates[str(chapter["id"])] = estimates
        # Missing historical sources must not overwrite a previously recorded estimate.
        if not missing or "estimated_minutes" not in chapter:
            chapter["estimated_minutes"] = sum(estimates.values())
            chapter["estimate_basis"] = (
                f"Heuristic: {units} reading units at {pace:g} units/minute, "
                f"2 reading + 6 practice + 4 review minutes per concept."
                + (f" Text is unavailable for {missing} source page(s); the estimate includes a page-count fallback." if missing else "")
            )
        chapter["estimate_details"] = {"reading_units": units, "reading_words_per_minute": pace,
                                      "source_page_count": len(keys), "missing_page_count": missing}
    unknown_completed = 0
    for task in result["tasks"]:
        if task.get("status") == "Completed":
            unknown_completed += "estimated_minutes" not in task
            continue
        estimates = chapter_estimates.get(str(task["chapterId"]), {})
        task["estimated_minutes"] = estimates.get(task.get("kind"), 5)
        task["estimate_basis"] = "Estimated from lecture text and concept overhead; adjust your reading pace in the planning profile."
    result["planning_profile"] = copy.deepcopy(profile)
    result["estimated_total_minutes"] = sum(int(task.get("estimated_minutes") or 0) for task in result["tasks"])
    result["estimated_remaining_minutes"] = sum(int(task.get("estimated_minutes") or 0) for task in result["tasks"] if task.get("status") != "Completed")
    result["estimate_basis"] = (
        "Heuristic workload estimate, not a measured or guaranteed completion time. "
        f"Default assumptions: {', '.join(profile.get('assumptions') or []) or 'none; profile values supplied'}."
        + (f" {unknown_completed} completed task(s) have no historical time estimate and are omitted from the total." if unknown_completed else "")
    )
    days = max(1, (_as_date(result["end"]) - _as_date(result["start"])).days + 1)
    result["capacity"] = {"available_minutes": days * profile["daily_minutes"],
                          "remaining_estimated_minutes": result["estimated_remaining_minutes"],
                          "over_capacity": result["estimated_remaining_minutes"] > days * profile["daily_minutes"]}
    return result


def _as_date(value):
    from datetime import date
    return date.fromisoformat(value)
