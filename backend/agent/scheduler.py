"""Deterministic, bounded scheduling and independent constraint validation."""
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from agent.plan_state import normalize_task_status, normalize_task_type


def today():
    return datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat()


def completed(task):
    return normalize_task_status(task.get("status")) == "completed"


def requirements(raw: dict, brief: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Scheduling requirements must be an object")
    start = date.fromisoformat(str(raw.get("start") or today()))
    deadline = date.fromisoformat(str(brief.get("deadline") or ""))
    target = deadline - timedelta(days=max(0, int(brief.get("earlyDays") or 0)))
    end = date.fromisoformat(str(raw.get("end") or target.isoformat()))
    if start < date.fromisoformat(today()) or end < start or end > deadline:
        raise ValueError("Choose dates from today through the course deadline")
    if (end - start).days > 365:
        raise ValueError("Schedule at most 366 days at a time")
    minutes = raw.get("daily_minutes")
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise ValueError("Enter daily study minutes between 1 and 1440")
    weekdays = raw.get("weekdays", list(range(7)))
    if not isinstance(weekdays, list) or not weekdays or any(type(x) is not int or x not in range(7) for x in weekdays):
        raise ValueError("Choose study weekdays (Monday=0, Sunday=6)")
    off = raw.get("off_dates", [])
    if not isinstance(off, list) or len(off) > 366:
        raise ValueError("Enter at most 366 excluded dates")
    off = [date.fromisoformat(str(x)).isoformat() for x in off]
    priority = raw.get("priority_chapter_ids", [])
    if not isinstance(priority, list) or len(priority) > 500:
        raise ValueError("Invalid chapter priorities")
    strategy = raw.get("strategy", "auto")
    if strategy not in ("auto", "new_first", "weak_first", "chapter_order"):
        raise ValueError("Unknown scheduling preference")
    return {"start": start.isoformat(), "end": end.isoformat(),
            "daily_minutes": minutes, "weekdays": sorted(set(weekdays)),
            "off_dates": sorted(set(off)), "priority_chapter_ids": list(dict.fromkeys(map(str, priority))),
            "strategy": strategy, "note": str(raw.get("note") or "")[:2000]}


def study_days(profile):
    first, last = date.fromisoformat(profile["start"]), date.fromisoformat(profile["end"])
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
            if (first + timedelta(days=i)).weekday() in profile["weekdays"]
            and (first + timedelta(days=i)).isoformat() not in profile["off_dates"]]


def last_scheduled_date(task):
    return max((slot["date"] for slot in task.get("schedule") or []), default=task.get("date") or "")


def chapter_weakness(evidence):
    """Rank documented gaps, with an unresolved exam taking precedence."""
    if (evidence.get("exam") or {}).get("passed") is False:
        return "exam_not_passed"
    mastery = evidence.get("mastery") or {}
    attempted = mastery.get("attempted", 0)
    if attempted:
        return "practice_gaps" if attempted > mastery.get("mastered", 0) else None
    if (evidence.get("exam") or {}).get("passed") is True:
        return None
    concepts = (evidence.get("practice") or {}).get("concepts") or []
    if any(int(concept.get("attempts") or 0) > 0 and int(concept.get("level") or 0) < 2
           for concept in concepts if isinstance(concept, dict)):
        return "practice_gaps"
    return None


def _task_slots(task):
    slots = task.get("schedule") or []
    if slots:
        return sorted(slots, key=lambda slot: slot["date"])
    if task.get("date"):
        return [{"date": task["date"], "minutes": task.get("estimated_minutes")}]
    return []


def schedule_summary(old, plan, profile, candidate, proposed_by):
    """Describe the schedule that is actually being published."""
    changes = []
    chapters = {str(chapter["id"]): chapter["title"] for chapter in plan["chapters"]}
    first_date = ""
    previous = {task["id"]: task for task in old["tasks"]}
    pending_chapters = set()
    completed_count = 0
    for task in plan["tasks"]:
        if completed(task):
            completed_count += 1
            continue
        chapter_id = str(task["chapterId"])
        pending_chapters.add(chapter_id)
        before = _task_slots(previous[task["id"]])
        after = _task_slots(task)
        if after:
            first_date = min(first_date or after[0]["date"], after[0]["date"])
        if before != after:
            title = task.get("title") or f"{task['kind']}: {chapters[chapter_id]}"
            changes.append({"task_id": task["id"], "title": title, "before": before, "after": after})

    strategy = candidate["strategy"]
    priorities = set(profile["priority_chapter_ids"]) & pending_chapters
    why = ["Your selected priority chapters are scheduled first."] if priorities else []
    if strategy == "weak_first":
        examples = []
        for chapter_id, evidence in candidate.get("weak_chapters", {}).items():
            if chapter_id not in pending_chapters or chapter_id in priorities:
                continue
            detail = "latest exam not passed" if evidence == "exam_not_passed" else "concepts still to master"
            examples.append(f'{chapters[chapter_id]} ({detail})')
        if examples:
            why.append("Earlier priority went to chapters with current gaps, including " + ", ".join(examples[:3]) + ".")
        else:
            why.append("With no other chapters showing a current gap, the remaining work follows chapter order.")
    elif strategy == "chapter_order":
        why.append("Tasks within the same priority group follow chapter order.")
    else:
        why.append("Within the same priority group, reading is placed before practice and review.")

    return {
        "strategy": strategy,
        "strategy_source": "preference" if profile["strategy"] != "auto" else proposed_by,
        "reason": " ".join(why),
        "first_date": first_date,
        "completed_preserved": completed_count,
        "changes": changes,
    }


def _review_minutes(chapter):
    return max(5, 4 * len(chapter.get("concepts") or []))


def estimate_times(plan, page_text, reports):
    estimates = {}
    chapters = {str(c["id"]): c for c in plan["chapters"]}
    for task in plan["tasks"]:
        if completed(task):
            continue
        chapter = chapters[str(task["chapterId"])]
        keys = {(int(s["document_id"]), int(s["page_number"])) for s in chapter.get("sources") or []}
        words = sum(len(re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", page_text.get(k, ""))) for k in keys)
        n = max(1, len(chapter.get("concepts") or []))
        minutes = {"Reading": max(5, math.ceil(words / 180) + 2 * n, len(keys)),
                   "Practice": max(10, 6 * n), "Review": _review_minutes(chapter)}[task["kind"]]
        evidence = reports.get(str(chapter["id"]), {})
        practice = evidence.get("practice") or {}
        if task["kind"] == "Practice" and task.get("status") == "In progress":
            # A transparent conservative estimate; no inferred completion.
            minutes = max(5, math.ceil(minutes * 0.75))
        estimates[task["id"]] = {"minutes": minutes,
            "basis": "Heuristic: text at 180 units/minute, concept overheads; active practice uses 75% of the initial estimate.",
            "has_learning_report": bool(practice or evidence.get("exam"))}
    return estimates


def schedule_required_review(plan, chapter, review):
    """Place a newly required Review in the published schedule's spare capacity."""
    minutes = _review_minutes(chapter)
    review.update({
        "date": "", "schedule": [], "estimated_minutes": minutes,
        "estimate_basis": "Estimated from the number of chapter concepts.",
    })
    profile = plan.get("scheduling_profile")
    if not plan.get("schedule_run_id") or not profile:
        return

    first_day = today()
    used = defaultdict(int)
    for task in plan["tasks"]:
        if task is review:
            continue
        slots = task.get("schedule") or []
        for slot in slots:
            used[slot["date"]] += slot["minutes"]
        if not slots and task.get("date"):
            used[task["date"]] += task.get("estimated_minutes") or profile["daily_minutes"]

        same_chapter = str(task.get("chapterId") or task.get("chapter_id")) == str(chapter["id"])
        earlier_step = normalize_task_type(task.get("kind") or task.get("type")) in {"read", "practice"}
        if same_chapter and earlier_step and not completed(task):
            last_slot = last_scheduled_date(task)
            if not last_slot:
                return
            first_day = max(first_day, last_slot)

    remaining = minutes
    review_slots = []
    for day in study_days(profile):
        if day < first_day:
            continue
        take = min(remaining, profile["daily_minutes"] - used[day])
        if take <= 0:
            continue
        review_slots.append({"date": day, "minutes": take})
        remaining -= take
        if remaining == 0:
            review.update({"date": review_slots[0]["date"], "schedule": review_slots})
            return


def propose_schedule(plan, profile, estimates, reports, strategy=None):
    strategy = strategy or profile["strategy"]
    if strategy == "auto":
        strategy = "new_first"
    if strategy not in ("new_first", "weak_first", "chapter_order"):
        raise ValueError("Unknown strategy")
    pending = [t for t in plan["tasks"] if not completed(t)]
    chapter_order = {str(c["id"]): i for i, c in enumerate(plan["chapters"])}
    priorities = {key: i for i, key in enumerate(profile["priority_chapter_ids"])}
    kinds = {"Reading": 0, "Practice": 1, "Review": 2}
    weak_chapters = {
        key: weakness for key in chapter_order
        if (weakness := chapter_weakness(reports.get(key, {})))
    }
    weak_rank = {"exam_not_passed": 0, "practice_gaps": 1}

    def rank(task):
        key = str(task["chapterId"])
        preference = (kinds[task["kind"]], chapter_order[key]) if strategy == "new_first" else (
            (weak_rank.get(weak_chapters.get(key), 2), chapter_order[key], kinds[task["kind"]]) if strategy == "weak_first"
            else (chapter_order[key], kinds[task["kind"]]))
        return (priorities.get(key, len(priorities)), *preference)

    days = study_days(profile)
    used = defaultdict(int)
    chapter_last_day = {}
    slots, unallocated = [], []
    for task in sorted(pending, key=rank):
        remaining = estimates[task["id"]]["minutes"]
        for day in days:
            if day < chapter_last_day.get(str(task["chapterId"]), ""):
                continue
            take = min(remaining, profile["daily_minutes"] - used[day])
            if take > 0:
                slots.append({"task_id": task["id"], "date": day, "minutes": take})
                used[day] += take
                remaining -= take
                chapter_last_day[str(task["chapterId"])] = day
            if remaining == 0:
                break
        if remaining:
            unallocated.append({"task_id": task["id"], "minutes": remaining})
    return {"strategy": strategy, "slots": slots, "unallocated": unallocated,
            "weak_chapters": weak_chapters if strategy == "weak_first" else {},
            "estimated_minutes": sum(x["minutes"] for x in estimates.values()),
            "available_minutes": len(days) * profile["daily_minutes"]}


def validate_schedule(plan, profile, estimates, candidate):
    errors, used, allocated = [], defaultdict(int), defaultdict(int)
    if profile["strategy"] != "auto" and candidate.get("strategy") != profile["strategy"]:
        errors.append("Candidate does not respect the explicit scheduling preference")
    allowed_days = set(study_days(profile))
    pending = {t["id"] for t in plan["tasks"] if not completed(t)}
    seen = set()
    slots = candidate.get("slots")
    if not isinstance(slots, list) or len(slots) > 10000:
        return {"valid": False, "errors": ["Invalid number of study sessions"]}
    for slot in slots:
        key, day, minutes = slot.get("task_id"), slot.get("date"), slot.get("minutes")
        if key not in pending or day not in allowed_days or type(minutes) is not int or minutes <= 0:
            errors.append("Invalid task, date or minutes")
            continue
        if (key, day) in seen:
            errors.append("Duplicate task session on one day")
        seen.add((key, day))
        used[day] += minutes
        allocated[key] += minutes
    for key in pending:
        if allocated[key] != estimates[key]["minutes"]:
            errors.append(f"Task {key} is not fully allocated")
    if any(value > profile["daily_minutes"] for value in used.values()):
        errors.append("Daily study capacity exceeded")
    if candidate.get("unallocated"):
        errors.append("Not enough study time before the deadline")
    for chapter in plan["chapters"]:
        chapter_tasks = [t for t in plan["tasks"] if str(t.get("chapterId")) == str(chapter["id"]) and not completed(t)]
        order = {"Reading": 0, "Practice": 1, "Review": 2}
        chapter_tasks.sort(key=lambda task: order.get(task.get("kind"), 99))
        previous_end = ""
        for task in chapter_tasks:
            dates = sorted(s["date"] for s in slots if s.get("task_id") == task["id"] and s.get("date") in allowed_days)
            if dates and dates[0] < previous_end:
                errors.append("Chapter tasks are scheduled before earlier learning steps finish")
            if dates:
                previous_end = dates[-1]
    return {"valid": not errors, "errors": errors[:20], "daily_minutes": dict(used)}
