import json
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from agent.llm import chat_model
from agent.skills import load_skill
from agent.web import search_pages
from db.auth import username_of
from db.courses import get_course
from db.qa import insert_record, load_page_bodies, recent_turns
from db.study_status import chapter_report, concept_report, course_study, review_report, wrong_report
from vector.rerank import rerank
from vector.segments import bridge_text, search, select_page_keys

PAGE_LIMIT = 4
CANDIDATES = 30
PAGE_CHARS = 8000
MAX_ANSWER = 8000
REFUSAL = "The lecture notes do not support an answer to this question."

ANSWER_SYSTEM = load_skill("qa")


def answer_question(user_id: int, course_id: int, question: str) -> dict:
    text = question.strip()
    if not text:
        raise ValueError("Write a question")
    if len(text) > 2000:
        raise ValueError("Question is too long")
    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    if _is_chat(text):
        return _store(course, user_id, text, _chat_reply(user_id, course_id, text), [], False, [], "chat")
    document_ids = [
        document["id"]
        for document in course["documents"]
        if document["ingest_status"] == "complete" and document["usable_page_count"] > 0
    ]
    pages, parsed, study, web_pages, account = _choose_and_answer(document_ids, user_id, course_id, text)
    answer = str(parsed.get("answer") or "").strip()
    if account:
        return _store(
            course,
            user_id,
            text,
            (answer or "No account name is available.")[:MAX_ANSWER],
            [],
            False,
            [],
            "account",
        )
    cited = []
    if pages:
        allowed = {(page["document_id"], page["page_number"]) for page in pages}
        names = {page["document_id"]: page["filename"] for page in pages}
        cited = _valid_pages(parsed, allowed, names)
    web = _valid_web(parsed, web_pages)
    lecture_answer = bool(
        parsed.get("supported") and cited and answer and not _declines(answer)
    )
    if lecture_answer and not web:
        return _store(course, user_id, text, answer[:MAX_ANSWER], cited, False, [])
    if web and answer:
        return _store(
            course,
            user_id,
            text,
            answer[:MAX_ANSWER],
            cited if lecture_answer else [],
            False,
            web,
        )
    if study:
        return _store(
            course,
            user_id,
            text,
            (answer or "No study record was found for this course.")[:MAX_ANSWER],
            [],
            False,
            [],
        )
    return _store(course, user_id, text, (answer or REFUSAL)[:MAX_ANSWER], [], True, [])


def list_questions(user_id: int, course_id: int) -> list[dict]:
    from db.qa import list_records

    return list_records(user_id, course_id)


MEMORY_TURNS = 10
MEMORY_CHARS = 500
MAX_TOOL_ROUNDS = 3


def _choose_and_answer(
    document_ids: list[int], user_id: int, course_id: int, question: str
) -> tuple[list[dict], dict, bool, list[dict], bool]:
    state = {"pages": [], "study": False, "searched": False, "record": None, "web": [], "web_done": False, "account": False}

    @tool
    def search_notes(query: str) -> str:
        """Search this course's lecture notes once. Use for a question about the lecture content."""
        if state["searched"]:
            return _format_pages(state["pages"]) + "\n\nThese are the only retrieved lecture pages."
        state["searched"] = True
        chosen = query.strip() or question
        state["pages"] = _retrieve(document_ids, chosen)[:PAGE_LIMIT]
        return _format_pages(state["pages"])

    @tool
    def search_web(query: str) -> str:
        """Open public web pages when the lecture notes have no answer or do not cover the question."""
        if not state["searched"]:
            return "Search the lecture notes before using the web."
        if state["web_done"]:
            return _format_web(state["web"]) + "\n\nThese are the only web pages."
        state["web_done"] = True
        chosen = query.strip() or question
        state["web"] = search_pages(chosen)
        if not state["web"]:
            return "No web pages were found."
        return _format_web(state["web"])

    @tool
    def account_info() -> str:
        """Read this student's username. Use when they ask their name, username, or who they are."""
        state["account"] = True
        return json.dumps({"username": username_of(user_id)}, ensure_ascii=False)

    @tool
    def review_status(chapter: str) -> str:
        """Read finished practice rounds, whether practice is still open, and exam results."""
        state["study"] = True
        return _study_json(review_report, user_id, course_id, chapter, state)

    @tool
    def concept_mastery(chapter: str) -> str:
        """Read whether each concept is mastered, has one correct answer, or is not mastered."""
        state["study"] = True
        return _study_json(concept_report, user_id, course_id, chapter, state)

    @tool
    def chapter_mastery(chapter: str) -> str:
        """Read whether each chapter's concepts are all mastered."""
        state["study"] = True
        return _study_json(chapter_report, user_id, course_id, chapter, state)

    @tool
    def wrong_answers(chapter: str) -> str:
        """Read submitted wrong practice answers and wrong exam answers."""
        state["study"] = True
        return _study_json(wrong_report, user_id, course_id, chapter, state)

    tools = [search_notes, search_web, account_info, review_status, concept_mastery, chapter_mastery, wrong_answers]
    by_name = {item.name: item for item in tools}
    messages = [
        SystemMessage(content=ANSWER_SYSTEM),
        *memory_messages(recent_turns(user_id, course_id, MEMORY_TURNS)),
        HumanMessage(content=question),
    ]
    model = chat_model().bind_tools(tools)
    prompted = False
    for round_index in range(MAX_TOOL_ROUNDS + 1):
        reply = model.invoke(messages)
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            parsed = _parse_reply(str(reply.content or "")) or {}
            if _asks_about_self(question) and not state["account"]:
                messages.append(reply)
                content = _run_tool(
                    by_name,
                    {"name": "account_info", "id": "account_info", "args": {}},
                    question,
                )
                messages.append(
                    HumanMessage(
                        content=(
                            "The student is asking about themself. "
                            "Answer only from this account record. "
                            "Do not use lecture notes or the web. "
                            "Return one JSON object only.\n\n"
                            + content
                        )
                    )
                )
                return state["pages"], _parse_model(messages), state["study"], state["web"], state["account"]
            if not prompted and not state["searched"] and not state["study"]:
                prompted = True
                messages.extend([reply, HumanMessage(content="Call the tools this question needs.")])
                continue
            if _needs_web(state, parsed):
                messages.append(reply)
                content = _run_tool(
                    by_name,
                    {"name": "search_web", "id": "search_web", "args": {"query": question}},
                    question,
                )
                messages.append(
                    HumanMessage(
                        content=(
                            "The lecture pages do not answer the question. "
                            "Use these web pages for the parts they cover, and copy each used page into web_sources. "
                            "Return one JSON object only.\n\n"
                            + content
                        )
                    )
                )
                return state["pages"], _parse_model(messages), state["study"], state["web"], state["account"]
            messages.append(reply)
            return state["pages"], parsed or _parse_model(messages), state["study"], state["web"], state["account"]
        messages.append(reply)
        allow_lookup = round_index < MAX_TOOL_ROUNDS or not state["searched"] or not state["web_done"]
        for index, call in enumerate(calls):
            name = call.get("name")
            if allow_lookup or name in {"search_notes", "search_web"}:
                content = _run_tool(by_name, call, question)
            else:
                content = "Use the lecture pages and web pages already returned."
            messages.append(ToolMessage(content=content, tool_call_id=call.get("id") or f"tool_{index}"))
        if round_index == MAX_TOOL_ROUNDS:
            messages.append(HumanMessage(content="Return one JSON object only, written for the student."))
            parsed = _parse_model(messages)
            if _needs_web(state, parsed):
                content = _run_tool(
                    by_name,
                    {"name": "search_web", "id": "search_web", "args": {"query": question}},
                    question,
                )
                messages.append(
                    HumanMessage(
                        content=(
                            "The lecture pages do not answer the question. "
                            "Use these web pages for the parts they cover, and copy each used page into web_sources. "
                            "Return one JSON object only.\n\n"
                            + content
                        )
                    )
                )
                parsed = _parse_model(messages)
            return state["pages"], parsed, state["study"], state["web"], state["account"]
    return state["pages"], {}, state["study"], state["web"], state["account"]


def _needs_web(state: dict, parsed: dict) -> bool:
    if state["web_done"] or state["study"] or state["account"] or not state["searched"]:
        return False
    return not _lecture_supported(parsed, state["pages"])


def _is_chat(question: str) -> bool:
    if _is_request(question):
        return False
    text = question.strip()
    if re.search(r"(你好|您好|谢谢|感谢|早上好|晚上好|hi\b|hello\b|hey\b|thanks\b|thank you)", text, re.I):
        return True
    return bool(re.match(r"^(我|i'm\b|i am\b|i have\b|my name\b|my age\b)", text, re.I))


def _is_request(question: str) -> bool:
    text = question.lower()
    markers = (
        "?",
        "？",
        "吗",
        "什么",
        "谁",
        "哪",
        "几",
        "多少",
        "为什么",
        "为何",
        "怎么",
        "怎样",
        "如何",
        "是不是",
        "对不对",
        "有没有",
        "能不能",
        "可不可以",
        "请问",
        "解释",
        "说明",
        "介绍",
        "总结",
        "概括",
        "列出",
        "讲一下",
        "讲讲",
        "说一下",
        "说说",
        "帮我",
        "告诉我",
        "复习",
        "掌握",
        "错题",
        "考试",
        "练习",
        "what",
        "who",
        "why",
        "how",
        "when",
        "where",
        "which",
        "explain",
        "define",
        "summarize",
        "tell me",
        "help me",
    )
    return any(marker in text for marker in markers)


def _chat_reply(user_id: int, course_id: int, text: str) -> str:
    messages = [
        SystemMessage(
            content=(
                "The student is chatting, not asking a course question. "
                "Reply in one or two casual sentences, in the same language they used. "
                "React to what they just said, the way a person would in conversation. "
                "Use plain sentences, not JSON. "
                "Do not mention tools, lecture notes, or searching."
            )
        ),
        *memory_messages(recent_turns(user_id, course_id, MEMORY_TURNS)),
        HumanMessage(content=text),
    ]
    reply = str(chat_model().invoke(messages).content or "").strip()
    return (reply or "好的。")[:MAX_ANSWER]


def _asks_about_self(question: str) -> bool:
    text = question.lower()
    markers = (
        "我名字",
        "我的名字",
        "我叫什么",
        "我是谁",
        "我的用户名",
        "我的账号",
        "my name",
        "who am i",
        "my username",
        "my account",
    )
    return any(marker in text for marker in markers)


def _lecture_supported(parsed: dict, pages: list[dict]) -> bool:
    answer = str(parsed.get("answer") or "")
    if not parsed.get("supported") or not pages or _declines(answer):
        return False
    allowed = {(page["document_id"], page["page_number"]) for page in pages}
    names = {page["document_id"]: page["filename"] for page in pages}
    return bool(_valid_pages(parsed, allowed, names))


def _declines(answer: str) -> bool:
    text = answer.lower()
    markers = (
        "do not contain",
        "does not contain",
        "don't contain",
        "do not cover",
        "does not cover",
        "cannot provide",
        "can't provide",
        "no specific information",
        "no information about",
        "if you want",
    )
    return any(marker in text for marker in markers)


def memory_messages(turns: list[dict]) -> list:
    messages = []
    for turn in turns[-MEMORY_TURNS:]:
        question = str(turn.get("question") or "").strip()
        answer = str(turn.get("answer") or "").strip()[:MEMORY_CHARS]
        if not question or not answer:
            continue
        messages.append(HumanMessage(content=question))
        messages.append(AIMessage(content=answer))
    return messages


def _run_tool(by_name: dict, call: dict, question: str) -> str:
    name = call.get("name")
    chosen = by_name.get(name)
    if chosen is None:
        return "That tool is not available."
    args = call.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    if name in {"search_notes", "search_web"}:
        args = {"query": str(args.get("query") or question)}
    elif name == "account_info":
        args = {}
    else:
        args = {"chapter": str(args.get("chapter") or "")}
    return str(chosen.invoke(args))


def _study_json(report, user_id: int, course_id: int, chapter: str, state: dict) -> str:
    if state["record"] is None:
        state["record"] = course_study(user_id, course_id)
    return json.dumps(report(state["record"], str(chapter or "")), ensure_ascii=False)


def _parse_model(messages: list) -> dict:
    parsed = _parse_reply(str(chat_model().invoke(messages).content))
    if parsed is None:
        messages.append(HumanMessage(content="Return one JSON object only."))
        parsed = _parse_reply(str(chat_model().invoke(messages).content))
    return parsed or {}


def _retrieve(document_ids: list[int], query: str) -> list[dict]:
    allowed_ids = set(document_ids)
    hits = [
        hit
        for hit in search(document_ids, query, limit=CANDIDATES)
        if hit["document_id"] in allowed_ids and str(hit.get("text") or "").strip()
    ]
    ordered = rerank(query, hits)
    if not ordered:
        return []
    preliminary = select_page_keys(ordered, PAGE_LIMIT, lambda hit: None)
    needed: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for document_id, page_number in preliminary:
        for key in ((document_id, page_number), (document_id, page_number + 1)):
            if key not in seen:
                seen.add(key)
                needed.append(key)
    stored = load_page_bodies(needed)
    scores: dict[tuple[int, int], float] = {}
    for hit in ordered:
        key = (int(hit["document_id"]), int(hit["page_number"]))
        score = float(hit.get("score") or 0)
        if key not in scores or score > scores[key]:
            scores[key] = score
    bridges: dict[tuple[int, int], str | None] = {}

    def bridge_page(hit: dict) -> int | None:
        key = (int(hit["document_id"]), int(hit["page_number"]))
        if key not in bridges:
            bridges[key] = _bridge_for(key, stored)
        bridge = bridges[key]
        if bridge and str(hit.get("text") or "").strip() == bridge:
            return key[1] + 1
        return None

    pages = []
    for key in select_page_keys(ordered, PAGE_LIMIT, bridge_page):
        row = stored.get(key)
        body = (row or {}).get("body") or ""
        if not str(body).strip():
            continue
        pages.append(
            {
                "document_id": key[0],
                "page_number": key[1],
                "filename": row["filename"],
                "body": body,
                "score": scores.get(key, 0),
            }
        )
    return pages


def _bridge_for(key: tuple[int, int], stored: dict) -> str | None:
    current = stored.get(key)
    following = stored.get((key[0], key[1] + 1))
    if current is None or following is None:
        return None
    bridge = bridge_text(str(current.get("body") or ""), str(following.get("body") or ""))
    return bridge.strip() if bridge else None


def _format_web(pages: list[dict]) -> str:
    blocks = []
    for page in pages:
        blocks.append(f"[web | {page['title']} | {page['url']}]\n{page['body']}")
    return "\n\n".join(blocks)


def _valid_web(parsed: dict, pages: list[dict]) -> list[dict]:
    allowed = {page["url"]: page["title"] for page in pages}
    chosen = []
    seen: set[str] = set()
    for item in parsed.get("web_sources") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if url not in allowed or url in seen:
            continue
        seen.add(url)
        chosen.append({"title": allowed[url], "url": url})
    if chosen:
        return chosen
    if pages and (_declines(str(parsed.get("answer") or "")) or not (parsed.get("supported") and parsed.get("cited_pages"))):
        return [{"title": page["title"], "url": page["url"]} for page in pages]
    return []


def _format_pages(pages: list[dict]) -> str:
    if not pages:
        return "No relevant pages were found."
    blocks = []
    for page in pages:
        body = str(page["body"]).strip()[:PAGE_CHARS]
        blocks.append(
            "[document_id="
            f"{page['document_id']} | {page['filename']} | page {page['page_number']}]\n{body}"
        )
    return "\n\n".join(blocks)


def _parse_reply(text: str) -> dict | None:
    raw = text.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _valid_pages(parsed: dict, allowed: set[tuple[int, int]], names: dict[int, str]) -> list[dict]:
    cited = []
    seen: set[tuple[int, int]] = set()
    for item in parsed.get("cited_pages") or []:
        key = _citation_key(item, allowed)
        if key is None or key not in allowed or key in seen:
            continue
        seen.add(key)
        cited.append(
            {
                "document_id": key[0],
                "filename": names[key[0]],
                "page_number": key[1],
            }
        )
    cited.sort(key=lambda item: (item["filename"], item["page_number"]))
    return cited


def _citation_key(item, allowed: set[tuple[int, int]]) -> tuple[int, int] | None:
    if isinstance(item, dict):
        try:
            return (int(item.get("document_id")), int(item.get("page_number")))
        except (TypeError, ValueError):
            return None
    try:
        page_number = int(item)
    except (TypeError, ValueError):
        return None
    matches = [key for key in allowed if key[1] == page_number]
    if len(matches) == 1:
        return matches[0]
    return None


def _store(
    course: dict,
    user_id: int,
    question: str,
    answer: str,
    cited: list[dict],
    refused: bool,
    web_sources: list[dict],
    origin: str = "",
) -> dict:
    record_id = insert_record(
        course["id"], user_id, question, answer, cited, refused, web_sources, origin
    )
    return {
        "qa_id": record_id,
        "course_id": course["id"],
        "course_name": course["name"],
        "question": question,
        "answer": answer,
        "cited_pages": [] if refused else cited,
        "web_sources": [] if refused else web_sources,
        "refused": refused,
        "origin": origin,
    }
