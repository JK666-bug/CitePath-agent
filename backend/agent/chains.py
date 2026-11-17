"""Shared LangChain LCEL helpers for CitePath agents."""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from agent.llm import chat_model


def parse_json_object(text: str) -> dict | None:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def message_text(message: BaseMessage | str | None) -> str:
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    return str(getattr(message, "content", "") or "")


def invoke_text(system: str, content: str) -> str:
    """One-shot system+human chat via LCEL; returns plain text."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system}"),
            ("human", "{content}"),
        ]
    )
    chain = prompt | chat_model() | StrOutputParser()
    return str(chain.invoke({"system": system, "content": content}) or "").strip()


def invoke_json(
    system: str,
    content: str,
    *,
    remind: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> dict | None:
    """One-shot JSON object call via LCEL; optionally retries once for JSON-only."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system}"),
            ("human", "{content}"),
        ]
    )
    model = chat_model()
    binds: dict = {}
    if temperature is not None:
        binds["temperature"] = temperature
    if max_tokens is not None:
        binds["max_tokens"] = max_tokens
    if timeout is not None:
        binds["timeout"] = timeout
    if binds:
        model = model.bind(**binds)
    chain = prompt | model | RunnableLambda(message_text) | RunnableLambda(parse_json_object)
    try:
        parsed = chain.invoke({"system": system, "content": content})
        if parsed is not None or not remind:
            return parsed
        retry = ChatPromptTemplate.from_messages(
            [
                ("system", "{system}"),
                ("human", "{content}"),
                ("human", "Return one JSON object only."),
            ]
        )
        return (retry | model | RunnableLambda(message_text) | RunnableLambda(parse_json_object)).invoke(
            {"system": system, "content": content}
        )
    except RuntimeError:
        raise
    except Exception as error:
        message = str(error)
        if "Insufficient token" in message:
            raise RuntimeError(
                "The model API has no remaining tokens. Check your API quota or switch LLM_PROVIDER."
            ) from error
        return None


def invoke_messages(messages: list[BaseMessage]) -> AIMessage:
    """Invoke the chat model on an explicit message list."""
    reply = chat_model().invoke(messages)
    if isinstance(reply, AIMessage):
        return reply
    return AIMessage(content=message_text(reply))


def system_human(system: str, content: str) -> list[BaseMessage]:
    return [SystemMessage(content=system), HumanMessage(content=content)]
