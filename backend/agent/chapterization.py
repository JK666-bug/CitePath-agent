from datetime import date, timedelta

from agent.plan import (
    _split_pages,
    parse_brief,
)
from db.chapterization import (
    ChapterizationConflict,
    choose_documents,
    prepare_chapterization,
    save_document_chapters,
)


def rebuild_chapters(
    user_id: int,
    course_id: int,
    token: str,
    document_ids: list[int],
    confirmed: bool,
) -> dict:
    state = prepare_chapterization(user_id, course_id)

    if token != state["token"]:
        raise ChapterizationConflict(
            "The course changed. Reload the PDF list and retry."
        )

    selected = choose_documents(
        state["documents"],
        document_ids,
        confirmed,
    )

    pages = [
        page
        for page in state["pages"]
        if int(page["document_id"]) in set(selected)
    ]

    if not pages:
        raise ValueError("No readable pages are available")

    try:
        brief = parse_brief(state["brief"])
    except ValueError as error:
        if str(error) != "Add a learning deadline before generating a plan":
            raise
        import json
        try:
            temporary = json.loads(state["brief"])
        except (TypeError, ValueError):
            temporary = {"note": state["brief"] or ""}
        if not isinstance(temporary, dict):
            temporary = {"note": str(state["brief"] or "")}
        temporary["deadline"] = (date.today() + timedelta(days=30)).isoformat()
        temporary["earlyDays"] = 0
        brief = parse_brief(json.dumps(temporary, ensure_ascii=False))

    # Existing Chapterizer accepts date arguments.
    # These are its existing context inputs, not daily-task scheduling.
    start = date.today().isoformat()
    end = (
        date.fromisoformat(brief["deadline"])
        - timedelta(days=brief["early_days"])
    ).isoformat()

    if end < start:
        end = start

    # Keep the existing prompt, parsing, per-PDF splitting and retry logic.
    chapters, reason = _split_pages(
        brief,
        pages,
        start,
        end,
    )

    return save_document_chapters(
        user_id=user_id,
        course_id=course_id,
        document_ids=selected,
        confirmed=confirmed,
        expected_token=state["token"],
        chapters=chapters,
        reason=reason,
    )