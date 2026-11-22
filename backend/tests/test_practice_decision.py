import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent.practice_decision import decide_next_question


CONCEPTS = [{"id": 1, "name": "Basics"}, {"id": 2, "name": "Applications"}]
PROGRESS = {1: {"level": 0, "streak": 0}, 2: {"level": 0, "streak": 1}}


class ChoosingModel:
    def __init__(self):
        self.replies = iter([
            AIMessage(content="", tool_calls=[{"name": "get_practice_snapshot", "args": {}, "id": "snapshot"}]),
            AIMessage(content="", tool_calls=[{"name": "choose_next_question", "args": {
                "concept_id": 2, "kind": "short", "reason": "Check application understanding after one correct answer."
            }, "id": "choose"}]),
        ])

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return next(self.replies)


class PracticeDecisionTest(unittest.TestCase):
    def test_model_can_choose_a_later_eligible_concept(self):
        with patch("agent.practice_decision.chat_model", return_value=ChoosingModel()):
            decision = decide_next_question(1, CONCEPTS, PROGRESS, [], {})
        self.assertEqual((decision["concept_id"], decision["kind"]), (2, "short"))
        self.assertEqual(decision["mode"], "agent")
        self.assertEqual([step["tool"] for step in decision["trace"]], ["get_practice_snapshot", "choose_next_question"])

    def test_model_failure_preserves_a_valid_next_question(self):
        with patch("agent.practice_decision.chat_model", side_effect=RuntimeError("unavailable")):
            decision = decide_next_question(1, CONCEPTS, PROGRESS, [], {})
        self.assertEqual((decision["concept_id"], decision["kind"]), (1, "mcq"))
        self.assertEqual(decision["mode"], "fallback")


if __name__ == "__main__":
    unittest.main()
