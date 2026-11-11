"""Report prose derived only from saved results, with no model or score changes."""
import copy


def _percentage(value):
    return f"{float(value) * 100:.6f}".rstrip("0").rstrip(".") + "%"


def _feedback_pending(item):
    status = item.get("explanation_status")
    if status is not None:
        return status in {"pending", "failed"}
    return str(item.get("explanation") or "").strip() in {"", "Review the cited page."}


def enrich_report(report: dict) -> dict:
    result = copy.deepcopy(report)
    for field in ("wrong", "questions"):
        for item in result.get(field) or []:
            if not isinstance(item, dict):
                continue
            if "explanation_status" not in item:
                item["explanation_status"] = (
                    "not_required" if item.get("correct") else
                    "pending" if _feedback_pending(item) else "ready"
                )
                item.setdefault("explanation_error", None)
                item.setdefault("explanation_attempts", 0)
    wrong = [item for item in result.get("wrong") or [] if isinstance(item, dict)]
    result["feedback_pending_count"] = sum(_feedback_pending(item) for item in wrong)
    rounds = result.get("rounds") or []
    threshold = result.get("passing_threshold", 0.8)
    descriptions = []
    for item in rounds:
        correct, total = item.get("correct_count"), item.get("total")
        if type(correct) is not int or type(total) is not int or total <= 0:
            continue
        descriptions.append(
            f"Round {item['round_number']}: {correct} of {total} answers correct "
            f"({_percentage(correct / total)}); "
            f"{'met' if item.get('passed') else 'did not meet'} the saved "
            f"{_percentage(threshold)} chapter pass mark."
        )
    result["round_summaries"] = descriptions
    outcome = result.get("outcome")
    if outcome in {"passed_round_1", "passed_round_2"}:
        result["summary"] = f"You passed this chapter in round {outcome[-1]}. This practice session is complete."
    elif outcome == "failed_after_2":
        result["summary"] = "This chapter session ended after two rounds without reaching its saved pass mark. Review the remaining weak concepts and their source pages."
    elif outcome == "legacy":
        result["summary"] = "This report preserves an earlier practice session. It has no official result under the current two-round rules."
    elif "passed" in result and type(result.get("total")) is int and result["total"] > 0:
        result["summary"] = (
            f"You answered {result['correct_count']} of {result['total']} questions correctly in this exam "
            f"({_percentage(result['correct_count'] / result['total'])}) and "
            f"{'met' if result['passed'] else 'did not meet'} its pass mark."
        )
    else:
        result["summary"] = "This saved record contains practice history. No official chapter result is available."
    if len(descriptions) > 1:
        result["summary"] += " Each round was assessed separately against the same pass mark."

    # A correct answer in the latest round resolves an earlier error; keep all
    # earlier errors in the history but offer revision guidance only for remaining gaps.
    remaining = result.get("remaining_weak_concepts")
    if remaining is None:
        remaining = list(dict.fromkeys(str(item.get("concept_name") or "") for item in wrong))
    latest_round = max((int(item.get("round_number") or 0) for item in rounds), default=0)
    guidance = []
    for concept in remaining:
        if not isinstance(concept, str) or not concept.strip():
            continue
        sources = []
        for item in wrong:
            if item.get("concept_name") != concept:
                continue
            if latest_round and item.get("round_number", latest_round) != latest_round:
                continue
            for source in item.get("sources") or []:
                if isinstance(source, dict) and source not in sources:
                    sources.append(copy.deepcopy(source))
        guidance.append({
            "concept": concept,
            "text": f"Re-read the cited pages for {concept}. Compare your saved response with the reference answer and marking points, then explain the concept in your own words.",
            "sources": sources,
        })
    result["review_guidance"] = guidance
    if result["feedback_pending_count"]:
        result["summary"] += (
            f" Explanations for {result['feedback_pending_count']} incorrect answer(s) are still unavailable; "
            "retry those explanations without resubmitting or changing your scores."
        )
    return result
