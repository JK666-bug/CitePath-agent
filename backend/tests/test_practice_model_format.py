import copy
import unittest
from unittest.mock import patch

from agent import practice


class PracticeModelFormatTest(unittest.TestCase):
    concept = {"id": 7, "name": "Sequence interface operations"}
    pages = [{"document_id": 4, "filename": "lecture.pdf", "page_number": 1, "body": "Sequence operations.", "position": 1}]

    def candidate(self, kind):
        return {"question": {"concept": self.concept["name"], "kind": kind, "prompt": "Explain sequences",
            "pages": [{"document_id": 4, "page_number": 1}],
            **({"options": ["Insert", "Delete", "Read", "Write"], "answer": "C"} if kind == "mcq"
               else {"rubric": ["Read", "Insert", "Delete"], "answer": "Read, insert and delete."})}}

    def test_option_text_is_rejected_then_repaired_without_relaxing_letter_rule(self):
        valid = self.candidate("mcq")
        invalid = copy.deepcopy(valid)
        invalid["question"]["answer"] = "Read"
        self.assertIsNone(practice.question_from_reply(invalid, self.concept, self.pages, "mcq"))
        with patch.object(practice, "_ask", side_effect=[invalid, valid]) as ask:
            result = practice._write_question(self.concept, self.pages, "mcq", None)
        self.assertEqual(result["answer"], "C")
        self.assertEqual(ask.call_count, 2)
        self.assertIn("ONE LETTER", ask.call_args_list[0].args[1])
        self.assertIn("previous candidate failed validation", ask.call_args.args[1])

    def test_short_array_and_six_points_are_rejected_then_repaired(self):
        valid = self.candidate("short")
        invalid = copy.deepcopy(valid)
        invalid["question"].update(answer=["Read", "Insert"], rubric=[f"Point {i}" for i in range(6)])
        self.assertIsNone(practice.question_from_reply(invalid, self.concept, self.pages, "short"))
        with patch.object(practice, "_ask", side_effect=[invalid, valid]):
            result = practice._write_question(self.concept, self.pages, "short", None)
        self.assertIsInstance(result["answer"], str)
        self.assertEqual(result["rubric"], valid["question"]["rubric"])

    def test_invalid_repair_stops_at_two_candidates_and_publishes_nothing(self):
        with patch.object(practice, "_ask", return_value=None) as ask, patch.object(practice, "store_round") as store:
            with self.assertRaisesRegex(RuntimeError, "new round was not saved"):
                practice._write_question(self.concept, self.pages, "short", None)
        self.assertEqual(ask.call_count, 2)
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
