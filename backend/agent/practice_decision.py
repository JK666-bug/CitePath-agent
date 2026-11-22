"""Choose the next practice target with a bounded model-controlled tool loop."""

import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from agent.llm import chat_model
from agent.practice_select import learn_kind, next_unmastered
from agent.skills import load_skill
from db.practice import latest_miss


def decide_next_question(user_id: int, concepts: list[dict], progress: dict, attempts: list[dict], prefs: dict) -> dict | None:
    eligible = {int(item["id"]): item for item in concepts if int(progress.get(int(item["id"]), {}).get("level") or 0) < 2}
    if not eligible:
        return None

    trace: list[dict] = []
    state = {"snapshot_read": False, "choice": None}

    @tool
    def get_practice_snapshot() -> dict:
        """Read unmastered concepts, current streaks, recent answers, and student preferences before choosing."""
        state["snapshot_read"] = True
        return {
            "concepts": [
                {"id": key, "name": item["name"],
                 "level": int(progress.get(key, {}).get("level") or 0),
                 "streak": int(progress.get(key, {}).get("streak") or 0)}
                for key, item in eligible.items()
            ],
            "recent_answers": [
                {"concept_id": row.get("concept_id"), "concept_name": row.get("concept_name"),
                 "kind": row.get("kind"), "correct": bool(row.get("correct"))}
                for row in attempts[-12:]
            ],
            "preferences": {key: prefs.get(key) for key in ("difficulty", "preferred_kind", "requirements")},
        }

    @tool
    def inspect_recent_mistake(concept_id: int) -> dict:
        """Inspect the student's latest wrong answer for one eligible concept when it may change the next question."""
        if not state["snapshot_read"] or concept_id not in eligible:
            return {"error": "Read the snapshot and choose an eligible concept first."}
        miss = latest_miss(user_id, concept_id)
        return {"concept_id": concept_id, "mistake": None if miss is None else {
            "question": str(miss.get("prompt") or "")[:500],
            "student_answer": str(miss.get("response") or "")[:500],
        }}

    @tool
    def choose_next_question(concept_id: int, kind: str, reason: str) -> dict:
        """Choose an eligible concept and mcq or short question. Explain the choice using observed learning evidence."""
        if not state["snapshot_read"] or concept_id not in eligible or kind not in {"mcq", "short"}:
            return {"error": "Read the snapshot, then choose an eligible concept and valid kind."}
        if not reason.strip():
            return {"error": "Give a brief reason for the decision."}
        state["choice"] = {"concept_id": concept_id, "kind": kind, "reason": reason.strip()[:300]}
        return {"accepted": True, **state["choice"]}

    tools = [get_practice_snapshot, inspect_recent_mistake, choose_next_question]
    by_name = {item.name: item for item in tools}
    try:
        model = chat_model().bind_tools(tools)
        messages = [SystemMessage(content=load_skill("practice")), HumanMessage(content="Choose the next practice question. Start by reading the snapshot.")]
        for _ in range(5):
            reply = model.invoke(messages)
            messages.append(reply)
            calls = getattr(reply, "tool_calls", None) or []
            if not calls:
                messages.append(HumanMessage(content="Use a tool to choose the next question; do not answer in prose."))
                continue
            for call in calls:
                name = call.get("name")
                args = call.get("args") or {}
                try:
                    observation = by_name[name].invoke(args) if name in by_name else {"error": "Unknown tool"}
                except (TypeError, ValueError, KeyError):
                    observation = {"error": "Invalid tool arguments"}
                trace.append({"tool": name, "arguments": args, "observation": observation if name == "choose_next_question" else {"read": "error" not in observation}})
                messages.append(ToolMessage(content=json.dumps(observation, ensure_ascii=False), tool_call_id=call["id"]))
                if state["choice"]:
                    break
            if state["choice"]:
                break
    except Exception:
        # A model outage must not prevent an already-started practice session from continuing.
        trace.append({"tool": "model", "observation": {"error": "Decision model unavailable"}})

    if state["choice"]:
        return {**state["choice"], "mode": "agent", "trace": trace}
    fallback = next_unmastered(concepts, progress)
    streak = int(progress.get(int(fallback["id"]), {}).get("streak") or 0)
    return {"concept_id": int(fallback["id"]), "kind": learn_kind(streak),
            "reason": "Used the next unmastered concept because the decision model did not complete.",
            "mode": "fallback", "trace": trace}
