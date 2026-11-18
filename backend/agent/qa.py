import json
import re

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, after_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.types import Command

from agent.chains import invoke_json, invoke_messages, invoke_text, message_text, parse_json_object
from agent.llm import chat_model
from agent.skills import load_skill
from agent.web import search_pages
from db.auth import username_of
from db.courses import get_course
from db.qa import insert_record, load_leading_pages, load_overview_pages, load_page_bodies, recent_turns
from db.study_status import chapter_report, concept_report, course_study, review_report, wrong_report
from vector.rerank import rerank
from vector.segments import search, select_page_keys

PAGE_LIMIT = 4
OVERVIEW_PAGE_LIMIT = 8
CANDIDATES = 30
PAGE_CHARS = 8000
MAX_ANSWER = 8000
REFUSAL = "The lecture notes do not support an answer to this question."
WEB_ASK = (
    "\n\nWould you like me to search the public web for this? "
    "Reply yes (for example 可以 / 好的) and I will search this turn automatically."
)
WEB_ENABLED_NOTE = (
    "\n\nWeb search is enabled for this turn. "
    "After search_notes (when PDFs are selected), you must also call search_web once "
    "before the final JSON answer, and combine lecture evidence with web evidence. "
    "If no lecture PDFs are selected, call search_web once and answer from the web pages."
)
WEB_FOLLOWUP_NOTE = (
    "\n\nThe student already saw a lecture-based answer and accepted a public web search. "
    "Call search_web once for the earlier topic. Do not call search_notes. "
    "Do not restate lecture or textbook content. Answer only from the web pages. "
    "If no usable web pages: say so briefly in the student's language and offer one short "
    "retry — do not invent general knowledge and do not repeat the lecture."
)
EMPTY_WEB = (
    "联网检索这次没有返回可用的公开网页。"
    "你可以换个关键词或说法，让我再搜一次。"
)

CHAT_WEB_SYSTEM = """You are chatting in CitePath course Q&A without selected lecture PDFs.
Reply in the student's language in plain text (no Markdown).
Use the provided public web pages when they help answer the question.
If the pages are weak, still give a helpful reply and say what is uncertain.
Return one JSON object only:
{"supported": false, "answer": string, "cited_pages": [], "web_sources": [{"title": string, "url": string}, ...]}
Put only web pages you actually used in web_sources."""


def answer_question(
    user_id: int,
    course_id: int,
    question: str,
    document_ids: list[int] | None = None,
    tab_id: str | None = None,
    include_web: bool = False,
) -> dict:
    text = question.strip()
    if not text:
        raise ValueError("Write a question")
    if len(text) > 2000:
        raise ValueError("Question is too long")
    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    # Affirmative replies to a prior "want me to search the web?" auto-enable
    # web for this turn — no need to flip the Web chip manually.
    web_topic = _web_followup_topic(user_id, course_id, text, tab_id)
    include_web = bool(include_web) or bool(web_topic)
    # Pure greetings / thanks: never search notes or ask about the web.
    if _is_greeting(text) and not include_web:
        return _store(
            course,
            user_id,
            text,
            _chat_reply(user_id, course_id, text, tab_id),
            [],
            False,
            [],
            "chat",
            tab_id,
        )
    # No PDFs selected -> casual chat; Web chip / yes-follow-up still allowed.
    if document_ids is not None and len(document_ids) == 0:
        if include_web:
            return _chat_with_web(
                course, user_id, course_id, text, tab_id, web_topic=web_topic
            )
        return _store(
            course,
            user_id,
            text,
            _chat_reply(user_id, course_id, text, tab_id),
            [],
            False,
            [],
            "chat",
            tab_id,
        )
    document_ids = _selected_document_ids(course, document_ids)
    pages, parsed, study, web_pages, account = _choose_and_answer(
        document_ids,
        user_id,
        course_id,
        text,
        tab_id,
        include_web=include_web,
        web_topic=web_topic,
    )
    answer = str(parsed.get("answer") or "").strip()
    # Only treat as account Q&A when the student actually asked about their identity.
    # Spurious account_info calls must not hide lecture evidence (e.g. a course code).
    if account and _asks_about_self(text):
        return _store(
            course,
            user_id,
            text,
            (answer or "No account name is available.")[:MAX_ANSWER],
            [],
            False,
            [],
            "account",
            tab_id,
        )
    cited = []
    if pages:
        allowed = {(page["document_id"], page["page_number"]) for page in pages}
        names = {page["document_id"]: page["filename"] for page in pages}
        cited = _valid_pages(parsed, allowed, names)
        # Attach sample pages when the model answered from notes but forgot cites.
        if (
            not cited
            and answer
            and not _declines(answer)
            and (
                _wants_course_overview(text)
                or bool(parsed.get("supported"))
                or _looks_lecture_grounded(answer)
            )
        ):
            cited = [
                {
                    "document_id": page["document_id"],
                    "filename": page["filename"],
                    "page_number": page["page_number"],
                }
                for page in pages
            ]
    web = _valid_web(parsed, web_pages)
    # Yes-follow-up after a web offer: web-only — never rehash lecture notes.
    if web_topic:
        if web and answer and not _declines(answer):
            return _store(
                course,
                user_id,
                text,
                answer[:MAX_ANSWER],
                [],
                False,
                web,
                "",
                tab_id,
            )
        return _store(
            course,
            user_id,
            text,
            EMPTY_WEB,
            [],
            True,
            [],
            "",
            tab_id,
        )
    # Valid cites + a real answer = lecture support, even if the model
    # wrongly set supported=false (e.g. "no textbook definition").
    lecture_answer = bool(cited and answer and not _declines(answer))
    # Notes answered and Web chip off — drop accidental web side trips.
    if lecture_answer and not include_web:
        return _store(course, user_id, text, answer[:MAX_ANSWER], cited, False, [], "", tab_id)
    if lecture_answer and include_web:
        return _store(
            course,
            user_id,
            text,
            answer[:MAX_ANSWER],
            cited,
            False,
            web,
            "",
            tab_id,
        )
    if web and answer:
        return _store(
            course,
            user_id,
            text,
            answer[:MAX_ANSWER],
            cited,
            False,
            web,
            "",
            tab_id,
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
            "",
            tab_id,
        )
    # Genuine small talk: no tools used and not a materials refusal.
    if answer and not cited and not web and not pages and not study and not _declines(answer):
        return _store(course, user_id, text, answer[:MAX_ANSWER], [], False, [], "chat", tab_id)
    soft = _with_web_ask(answer or REFUSAL, include_web=include_web)
    return _store(course, user_id, text, soft[:MAX_ANSWER], [], True, [], "", tab_id)


def list_questions(user_id: int, course_id: int) -> list[dict]:
    from db.qa import list_records

    return list_records(user_id, course_id)


def delete_question_tab(user_id: int, course_id: int, tab_id: str) -> None:
    from db.qa import delete_tab

    delete_tab(user_id, course_id, tab_id)


MEMORY_TURNS = 10
MEMORY_CHARS = 500
MAX_TOOL_ROUNDS = 3


def _selected_document_ids(course: dict, document_ids: list[int] | None) -> list[int]:
    ready = {
        int(document["id"])
        for document in course.get("documents") or []
        if document.get("ingest_status") == "complete"
        and int(document.get("usable_page_count") or 0) > 0
        and document.get("is_active", document.get("active", True))
        and document.get("kind", "lecture") == "lecture"
    }
    if not ready:
        raise ValueError("Upload a readable PDF before asking")
    if document_ids is None:
        return sorted(ready)
    chosen = []
    seen: set[int] = set()
    for item in document_ids:
        document_id = int(item)
        if document_id not in ready:
            raise ValueError("Select readable PDFs from this course")
        if document_id in seen:
            continue
        seen.add(document_id)
        chosen.append(document_id)
    if not chosen:
        raise ValueError("Select at least one readable PDF")
    return chosen


def _choose_and_answer(
    document_ids: list[int],
    user_id: int,
    course_id: int,
    question: str,
    tab_id: str | None = None,
    include_web: bool = False,
    web_topic: str | None = None,
) -> tuple[list[dict], dict, bool, list[dict], bool]:
    state = {
        "pages": [],
        "study": False,
        "searched": False,
        "record": None,
        "web": [],
        "web_done": False,
        "account": False,
        "nudged": False,
        "nudged_web": False,
    }
    topic = str(web_topic or "").strip() or question

    @tool
    def search_notes(query: str) -> str:
        """Load lecture PDF pages. For course/PPT overview questions, samples pages across the deck for a summary; otherwise searches by meaning."""
        if web_topic:
            return (
                "This turn is a web follow-up. Do not search lecture notes. "
                "Call search_web for the earlier topic instead."
            )
        if state["searched"]:
            return _format_pages(state["pages"]) + "\n\nThese are the only retrieved lecture pages."
        state["searched"] = True
        chosen = query.strip() or topic
        # Overview asks need a thematic summary, not "does this keyword appear".
        if _wants_course_overview(topic) or _wants_course_overview(chosen):
            state["pages"] = _pages_from_rows(
                load_overview_pages(document_ids, OVERVIEW_PAGE_LIMIT)
            )
            header = (
                "Overview sample pages from the selected lecture PDFs. "
                "Summarize what the materials cover (themes, topics, structure). "
                "Do not check whether the student's exact words appear as a keyword.\n\n"
            )
            return header + _format_pages(state["pages"])
        state["pages"] = _retrieve(document_ids, chosen)[:PAGE_LIMIT]
        if not state["pages"]:
            state["pages"] = _pages_from_rows(
                load_leading_pages(document_ids, PAGE_LIMIT)
            )
        return _format_pages(state["pages"])

    @tool
    def search_web(query: str) -> str:
        """Open public web pages. Prefer after lecture notes when PDFs are selected; allowed immediately when Web search is enabled."""
        if not include_web and not state["searched"]:
            return "Search the lecture notes before using the web, or ask the student to turn on Web search."
        if state["web_done"]:
            return _format_web(state["web"]) + "\n\nThese are the only web pages."
        state["web_done"] = True
        chosen = query.strip() or topic
        # Ignore bare yes-replies as the search string.
        if _accepts_web(chosen) and topic != chosen:
            chosen = topic
        state["web"] = search_pages(chosen)
        if not state["web"]:
            return "No web pages were found."
        return _format_web(state["web"])

    @tool
    def account_info() -> str:
        """Read this student's username. Call ONLY when they ask their name, username, or who they are — never for course codes, lecture tokens, or topic keywords."""
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
        """Read chapter pass outcomes, separate round scores and whether its concepts are all mastered."""
        state["study"] = True
        return _study_json(chapter_report, user_id, course_id, chapter, state)

    @tool
    def wrong_answers(chapter: str) -> str:
        """Read submitted wrong practice answers and wrong exam answers."""
        state["study"] = True
        return _study_json(wrong_report, user_id, course_id, chapter, state)

    tools = [
        search_notes,
        search_web,
        account_info,
        review_status,
        concept_mastery,
        chapter_mastery,
        wrong_answers,
    ]

    @after_model(can_jump_to=["model", "end"])
    def nudge_search_notes(agent_state, runtime):
        del runtime
        messages = list(agent_state.get("messages") or [])
        if not messages:
            return None
        last = messages[-1]
        calls = getattr(last, "tool_calls", None) or []
        if calls:
            return None
        raw = message_text(last).strip()
        parsed = parse_json_object(raw) or {}
        answer_text = str(parsed.get("answer") or raw)
        if include_web and not state["web_done"] and not state["nudged_web"]:
            state["nudged_web"] = True
            return Command(
                goto="model",
                update={
                    "messages": [
                        HumanMessage(
                            content=(
                                "Web search is enabled. Call search_web once now, "
                                "then return one JSON object from the web pages only."
                                if web_topic
                                else (
                                    "Web search is enabled. Call search_web once now, "
                                    "then return one JSON object"
                                    + (
                                        " that uses lecture pages and web pages."
                                        if state["searched"]
                                        else " from the web pages."
                                    )
                                )
                            )
                        )
                    ]
                },
            )
        # Yes-follow-up: web-only — never force another lecture search.
        if web_topic:
            return None
        # If PDFs are selected and notes were never searched, force one search
        # even when the model asks for clarification instead of answering.
        # Skip greetings / account-name small talk.
        if state["nudged"] or state["searched"] or state["study"] or state["account"]:
            return None
        if _is_greeting(topic) or _asks_about_self(topic):
            return None
        state["nudged"] = True
        return Command(
            goto="model",
            update={
                "messages": [
                    HumanMessage(
                        content=(
                            "Call search_notes once for this course's selected PDFs "
                            f"using a query about: {topic}. "
                            "Then answer from the returned pages as one JSON object. "
                            "Do not ask which course or topic this is from before searching."
                            + (
                                " After that, call search_web once before the final answer."
                                if include_web
                                else ""
                            )
                        )
                    )
                ]
            },
        )

    system_prompt = load_skill("qa") + (
        WEB_FOLLOWUP_NOTE if web_topic else (WEB_ENABLED_NOTE if include_web else "")
    )
    agent = create_agent(
        model=chat_model(),
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            ModelCallLimitMiddleware(run_limit=MAX_TOOL_ROUNDS + 3, exit_behavior="end"),
            nudge_search_notes,
        ],
        name="citepath-qa",
    )
    if web_topic:
        agent_text = (
            f"The student accepted a public web search for this earlier question:\n{topic}\n"
            f"Their reply was: {question}\n"
            "Call search_web once for that topic. Do not call search_notes. "
            "Return one JSON answer from the web pages only. "
            "If none are usable, say so briefly without repeating lecture content."
        )
    else:
        agent_text = question
    result = agent.invoke(
        {
            "messages": [
                *memory_messages(recent_turns(user_id, course_id, MEMORY_TURNS, tab_id)),
                HumanMessage(content=agent_text),
            ]
        }
    )
    parsed = _final_parsed(result.get("messages") or [], state)
    if include_web and not state["web_done"]:
        state["web_done"] = True
        state["web"] = search_pages(topic)
        if state["web"]:
            if web_topic:
                refreshed = _resynthesize_with_web(
                    topic, [], state["web"], parsed, followup=True
                )
            else:
                refreshed = _resynthesize_with_web(
                    topic, state["pages"], state["web"], parsed
                )
            if refreshed:
                parsed = refreshed
        elif web_topic:
            parsed = {
                "supported": False,
                "answer": EMPTY_WEB,
                "cited_pages": [],
                "web_sources": [],
            }
    return state["pages"], parsed, state["study"], state["web"], state["account"]


def _final_parsed(messages: list, state: dict) -> dict:
    raw = ""
    for item in reversed(messages):
        if isinstance(item, AIMessage) and not (getattr(item, "tool_calls", None) or []):
            raw = message_text(item).strip()
            if raw:
                break
    parsed = parse_json_object(raw) or {}
    if not parsed.get("answer") and raw and not (
        state["searched"] or state["study"] or state["account"] or state["web"]
    ):
        return {
            "supported": False,
            "answer": raw,
            "cited_pages": [],
            "web_sources": [],
        }
    if parsed.get("answer"):
        return parsed
    if raw:
        retry = parse_json_object(
            invoke_text(
                load_skill("qa"),
                "Return one JSON object only, written for the student.\n\n"
                f"Draft answer to rewrite as JSON:\n{raw}",
            )
        )
        if retry:
            return retry
    return parsed or {}


def _resynthesize_with_web(
    question: str,
    pages: list[dict],
    web: list[dict],
    previous: dict,
    followup: bool = False,
) -> dict | None:
    draft = str(previous.get("answer") or "").strip()
    if followup:
        return invoke_json(
            load_skill("qa") + WEB_FOLLOWUP_NOTE,
            (
                f"Question: {question}\n\n"
                f"Web pages:\n{_format_web(web)}\n\n"
                + (f"Draft so far:\n{draft}\n\n" if draft else "")
                + "Return one JSON object only from the web pages. "
                "Do not mention or restate lecture notes."
            ),
        )
    return invoke_json(
        load_skill("qa") + WEB_ENABLED_NOTE,
        (
            f"Question: {question}\n\n"
            f"Lecture pages:\n{_format_pages(pages)}\n\n"
            f"Web pages:\n{_format_web(web)}\n\n"
            + (f"Draft so far:\n{draft}\n\n" if draft else "")
            + "Return one JSON object only that uses both sources where helpful."
        ),
    )


def _offers_web(answer: str) -> bool:
    text = str(answer or "").lower()
    markers = (
        "search the web",
        "search online",
        "public web",
        "web chip",
        "want me to search",
        "shall i search",
        "look online",
        "find online",
        "联网",
        "上网",
        "搜索网页",
        "网上搜索",
        "网上查",
        "上网查",
        "上网搜",
        "要不要我搜",
        "是否需要我搜索",
        "需要我帮你联网",
        "需要我帮你上网",
        "帮你联网查",
        "帮你上网查",
        "要我联网",
        "要我上网",
        "查一份更",
        "查一下更",
    )
    return any(marker in text for marker in markers)


def _rejects_web(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    markers = (
        "不用",
        "不要",
        "不需要",
        "不可以",
        "先不用",
        "算了",
        "no",
        "nope",
        "don't",
        "do not",
        "no thanks",
        "no need",
    )
    return any(marker in raw for marker in markers)


def _accepts_web(text: str) -> bool:
    """True for short yes / 可以-style replies that accept a web-search offer."""
    raw = str(text or "").strip().lower()
    if not raw or _rejects_web(raw):
        return False
    compact = re.sub(r"[\s\.\!\?。！？，,、]+", "", raw)
    yes = {
        "yes",
        "y",
        "ok",
        "okay",
        "sure",
        "please",
        "yep",
        "yeah",
        "goahead",
        "可以",
        "好",
        "好的",
        "行",
        "要",
        "需要",
        "嗯",
        "对",
        "是",
        "是的",
        "搜吧",
        "查吧",
        "联网",
        "请联网",
        "帮我搜",
        "帮我查",
        "搜索吧",
        "查一下",
        "搜一下",
    }
    if compact in yes or raw in yes:
        return True
    markers = (
        "search the web",
        "search online",
        "yes please",
        "go ahead",
        "please search",
        "请搜索",
        "请联网",
        "帮我联网",
        "帮我搜索",
        "可以搜",
        "可以查",
        "联网查",
        "联网搜",
    )
    return any(marker in raw for marker in markers)


def _web_followup_topic(
    user_id: int,
    course_id: int,
    text: str,
    tab_id: str | None,
) -> str | None:
    """If the student accepted a prior web offer, return that earlier question topic."""
    if not _accepts_web(text):
        return None
    turns = recent_turns(user_id, course_id, MEMORY_TURNS, tab_id)
    if not turns:
        return None
    last = turns[-1]
    if not _offers_web(str(last.get("answer") or "")):
        return None
    prior = str(last.get("question") or "").strip()
    return prior or None


def _with_web_ask(answer: str, *, include_web: bool) -> str:
    text = str(answer or "").strip() or REFUSAL
    if include_web or _offers_web(text):
        return text
    return (text.rstrip() + WEB_ASK)[:MAX_ANSWER]


def _chat_reply(
    user_id: int,
    course_id: int,
    text: str,
    tab_id: str | None = None,
) -> str:
    reply = invoke_messages(
        [
            SystemMessage(
                content=(
                    "The student is chatting casually and has not selected lecture PDFs. "
                    "Reply in one or two casual sentences, in the same language they used. "
                    "React to what they just said, the way a person would in conversation. "
                    "Use plain sentences, not JSON. "
                    "Do not search lecture notes or invent course facts. "
                    "Do not mention tools, lecture notes, or searching. "
                    "If they want public web results after you offered a search, "
                    "a short yes is enough; they do not need the Web chip."
                )
            ),
            *memory_messages(recent_turns(user_id, course_id, MEMORY_TURNS, tab_id)),
            HumanMessage(content=text),
        ]
    )
    return (message_text(reply).strip() or "好的。")[:MAX_ANSWER]


def _chat_with_web(
    course: dict,
    user_id: int,
    course_id: int,
    text: str,
    tab_id: str | None = None,
    web_topic: str | None = None,
) -> dict:
    topic = str(web_topic or "").strip() or text
    web = search_pages(topic)
    student_line = (
        f"Earlier question: {topic}\nStudent accepted web search with: {text}"
        if web_topic
        else text
    )
    parsed = invoke_json(
        CHAT_WEB_SYSTEM,
        (
            f"Student message:\n{student_line}\n\n"
            f"Web pages:\n{_format_web(web) if web else 'No web pages were found.'}"
        ),
    ) or {}
    answer = str(parsed.get("answer") or "").strip()
    if not answer:
        answer = invoke_text(
            (
                "The student is chatting without lecture PDFs. Web search is on. "
                "Reply helpfully in their language using the web pages when useful. "
                "Plain sentences only, not JSON."
            ),
            (
                f"Student: {student_line}\n\n"
                f"Web pages:\n{_format_web(web) if web else 'No web pages were found.'}"
            ),
        )
    sources = _valid_web(parsed, web) if web else []
    if web and not sources and answer:
        sources = [{"title": page["title"], "url": page["url"]} for page in web[:3]]
    return _store(
        course,
        user_id,
        text,
        (answer or "I could not find useful web results.")[:MAX_ANSWER],
        [],
        False,
        sources,
        "chat" if not sources else "",
        tab_id,
    )


def _is_greeting(text: str) -> bool:
    """True for short hellos / thanks with no course question."""
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    compact = re.sub(r"[\s\.\!\?。！？，,、~～]+", "", raw)
    greetings = {
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "你好",
        "您好",
        "哈喽",
        "嗨",
        "早",
        "早安",
        "早上好",
        "午安",
        "晚上好",
        "在吗",
        "在不在",
        "thanks",
        "thankyou",
        "thx",
        "ty",
        "谢谢",
        "多谢",
        "感谢",
        "好的谢谢",
        "拜拜",
        "再见",
        "bye",
        "goodbye",
    }
    if compact in greetings:
        return True
    # Very short and only greeting words.
    if len(compact) <= 8 and any(
        compact.startswith(word) for word in ("hi", "hey", "hello", "你好", "您好", "嗨")
    ):
        return True
    return False


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
        "insufficient evidence",
        "没有找到",
        "无法确定",
        "没有可用",
        "找不到",
        "未能找到",
        "不支持回答",
        "无法回答",
        "请告诉我具体",
    )
    # Do not treat a trailing web offer ("If you want…") as a refusal when
    # the body already answered from the lecture.
    return any(marker in text for marker in markers)


def _looks_lecture_grounded(answer: str) -> bool:
    text = answer.lower()
    if len(answer.strip()) < 80:
        return False
    markers = (
        "lecture",
        "slide",
        "deck",
        "course",
        "page",
        "p.",
        "l0",
        "讲义",
        "课件",
        "页",
    )
    return any(marker in text for marker in markers)


def _wants_course_overview(question: str) -> bool:
    text = question.lower()
    markers = (
        "ppt",
        "pptx",
        "slide",
        "deck",
        "lecture",
        "course",
        "syllabus",
        "talk about",
        "talked about",
        "about",
        "讲义",
        "课件",
        "这门课",
        "课程",
        "讲了什么",
        "讲什么",
        "关于什么",
        "什么内容",
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


def _study_json(report, user_id: int, course_id: int, chapter: str, state: dict) -> str:
    if state["record"] is None:
        state["record"] = course_study(user_id, course_id)
    return json.dumps(report(state["record"], str(chapter or "")), ensure_ascii=False)


def _pages_from_rows(rows: list[dict]) -> list[dict]:
    pages = []
    for row in rows:
        body = str(row.get("body") or "").strip()
        if not body:
            continue
        pages.append(
            {
                "document_id": int(row["document_id"]),
                "page_number": int(row["page_number"]),
                "filename": row["filename"],
                "body": body,
                "score": 0,
            }
        )
    return pages


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
    scores: dict[tuple[int, int], float] = {}
    for hit in ordered:
        key = (int(hit["document_id"]), int(hit["page_number"]))
        score = float(hit.get("score") or 0)
        if key not in scores or score > scores[key]:
            scores[key] = score

    def bridge_page(hit: dict) -> int | None:
        # Indexed on the chunk: 0 = one page; otherwise return companion page too.
        to = int(hit.get("bridge_to") or 0)
        page = int(hit.get("page_number") or 0)
        if to <= 0 or to == page:
            return None
        return to

    keys = select_page_keys(ordered, PAGE_LIMIT, bridge_page)
    stored = load_page_bodies(keys)
    pages = []
    for key in keys:
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


def _format_web(pages: list[dict]) -> str:
    blocks = []
    for page in pages:
        blocks.append(f"[web | {page['title']} | {page['url']}]\n{page['body']}")
    return "\n\n".join(blocks)


def _valid_web(parsed: dict, pages: list[dict]) -> list[dict]:
    """Only keep web pages the model explicitly cited — never dump every search hit."""
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
    return chosen


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
    tab_id: str | None = None,
) -> dict:
    stored = insert_record(
        course["id"],
        user_id,
        question,
        answer,
        cited,
        refused,
        web_sources,
        origin,
        tab_id,
    )
    return {
        "qa_id": int(stored["qa_id"]),
        "course_id": course["id"],
        "course_name": course["name"],
        "question": question,
        "answer": answer,
        "cited_pages": [] if refused else cited,
        "web_sources": [] if refused else web_sources,
        "refused": refused,
        "origin": origin,
        "tab_id": stored["tab_id"],
        "tab_title": stored["tab_title"],
    }
