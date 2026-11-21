"""Task identity is independent of scheduling and chapter generation."""
import copy

from agent.plan_state import normalize_task_type


def chapter_task(chapter: dict, kind: str) -> dict:
    chapter_id = str(chapter["id"])
    label = "Read" if kind == "Reading" else kind
    return {
        "id": f"{kind.lower()}-{chapter_id}", "chapterId": chapter_id,
        "title": f"{label}: {chapter['title']}", "kind": kind,
        "date": "", "schedule": [], "status": "Not started",
        "completion_source": "", "sources": copy.deepcopy(chapter.get("sources") or []),
        "concepts": list(chapter.get("concepts") or []),
    }


def ensure_chapter_tasks(plan: dict) -> tuple[dict, int]:
    result = copy.deepcopy(plan)
    tasks = result.setdefault("tasks", [])
    existing = {
        (str(t.get("chapterId") or t.get("chapter_id") or ""),
         normalize_task_type(t.get("kind") or t.get("type")))
        for t in tasks
    }
    added = 0
    for chapter in result.get("chapters") or []:
        chapter_id = str(chapter["id"])
        for kind in ("Reading", "Practice"):
            if (chapter_id, normalize_task_type(kind)) in existing:
                continue
            tasks.append(chapter_task(chapter, kind))
            added += 1
    return result, added
