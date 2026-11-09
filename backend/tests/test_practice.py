import unittest

from agent.practice import build_practice_report, question_from_reply
from agent.practice_select import (
    all_mastered,
    build_review_queue,
    learn_kind,
    next_unmastered,
    record_learn,
    record_review,
    review_set,
)


CHAPTER = [
    {"id": 1, "name": "Goals"},
    {"id": 2, "name": "Planning"},
    {"id": 3, "name": "Review"},
    {"id": 4, "name": "Diagrams"},
]


class PracticeSelectTest(unittest.TestCase):
    def test_learns_the_earliest_unmastered_concept_until_two_correct_answers(self):
        progress = {}
        concept = next_unmastered(CHAPTER, progress)
        self.assertEqual(concept["name"], "Goals")
        self.assertEqual(learn_kind(0), "mcq")
        level, streak = record_learn(True, 0)
        self.assertEqual((level, streak), (0, 1))
        self.assertEqual(learn_kind(streak), "short")
        level, streak = record_learn(False, streak)
        self.assertEqual((level, streak), (0, 0))
        level, streak = record_learn(True, streak)
        level, streak = record_learn(True, streak)
        self.assertEqual((level, streak), (2, 2))
        progress[1] = {"level": level, "streak": streak}
        self.assertEqual(next_unmastered(CHAPTER, progress)["name"], "Planning")

    def test_review_mixes_up_to_three_mastered_concepts(self):
        progress = {
            1: {"level": 2, "streak": 2, "updated_at": "2026-11-01 00:00:00"},
            2: {"level": 2, "streak": 2, "updated_at": "2026-11-08 00:00:00"},
            3: {"level": 0, "streak": 0, "updated_at": ""},
            4: {"level": 2, "streak": 2, "updated_at": "2026-11-02 00:00:00"},
        }
        chosen = review_set(CHAPTER, progress)
        self.assertEqual([item["name"] for item in chosen], ["Goals", "Diagrams", "Planning"])
        queue = build_review_queue([item["id"] for item in chosen], shuffle=lambda items: items.reverse())
        self.assertEqual(len(queue), 6)
        self.assertEqual(sorted(item["kind"] for item in queue), ["mcq", "mcq", "mcq", "short", "short", "short"])
        self.assertEqual(record_review(0), (0, 0))
        self.assertEqual(record_review(1), (2, 2))
        self.assertEqual(record_review(2), (2, 2))

    def test_a_finished_chapter_starts_again_only_when_every_concept_is_mastered(self):
        mastered = {item["id"]: {"level": 2, "streak": 2} for item in CHAPTER}
        self.assertTrue(all_mastered(CHAPTER, mastered))
        mastered[3] = {"level": 0, "streak": 0}
        self.assertFalse(all_mastered(CHAPTER, mastered))
        self.assertFalse(all_mastered([], {}))


class PracticeReportTest(unittest.TestCase):
    def test_counts_attempts_and_keeps_wrong_answers(self):
        report = build_practice_report(
            [{"id": 1, "name": "Goals"}, {"id": 2, "name": "Planning"}],
            {1: {"level": 2}, 2: {"level": 2}},
            [
                {
                    "question_id": 8,
                    "concept_id": 1,
                    "concept_name": "Goals",
                    "kind": "mcq",
                    "phase": "learn",
                    "prompt": "What is the goal?",
                    "response": "B",
                    "correct": False,
                    "answer": "A. Study from lectures",
                    "explanation": "The page says study.",
                    "sources": [{"document_id": 6, "page_number": 1, "position": 1, "filename": "notes.pdf"}],
                },
                {
                    "question_id": 9,
                    "concept_id": 1,
                    "concept_name": "Goals",
                    "kind": "mcq",
                    "phase": "learn",
                    "prompt": "What is the goal?",
                    "response": "A",
                    "correct": True,
                    "answer": "A. Study from lectures",
                    "explanation": "",
                    "sources": [],
                },
            ],
        )
        self.assertEqual(report["question_count"], 2)
        self.assertEqual(report["correct_count"], 1)
        self.assertEqual(report["wrong_count"], 1)
        self.assertEqual(report["concepts"][0]["attempts"], 2)
        self.assertEqual(report["concepts"][0]["correct"], 1)
        self.assertEqual(report["concepts"][1]["attempts"], 0)
        self.assertEqual(report["wrong"][0]["concept_name"], "Goals")
        self.assertEqual(report["wrong"][0]["answer"], "A. Study from lectures")
        self.assertEqual(len(report["questions"]), 2)
        self.assertEqual([item["correct"] for item in report["questions"]], [False, True])
    def test_keeps_the_requested_concept_and_full_options(self):
        concept = {"id": 10, "name": "CitePath learning agent goals"}
        pages = [
            {
                "document_id": 6,
                "page_number": 1,
                "filename": "notes.pdf",
                "position": 1,
                "body": "The agent helps students study.",
            }
        ]
        question = question_from_reply(
            {
                "question": {
                    "concept": "CitePath learning agent goals",
                    "kind": "mcq",
                    "prompt": "What does the agent help students do?",
                    "options": ["Study from lectures", "A", "Edit the database", "Skip citations"],
                    "answer": "A",
                    "pages": [{"document_id": 6, "page_number": 1}],
                }
            },
            concept,
            pages,
            "mcq",
        )
        self.assertIsNone(question)
        question = question_from_reply(
            {
                "question": {
                    "concept": "CitePath learning agent goals",
                    "kind": "mcq",
                    "prompt": "What does the agent help students do?",
                    "options": ["Study from lectures", "Draw a map", "Edit the database", "Skip citations"],
                    "answer": "A",
                    "pages": [{"document_id": 6, "page_number": 1}],
                }
            },
            concept,
            pages,
            "mcq",
        )
        self.assertEqual(question["concept_name"], "CitePath learning agent goals")
        self.assertEqual(question["sources"][0]["position"], 1)

    def test_rejects_a_different_kind(self):
        question = question_from_reply(
            {
                "question": {
                    "concept": "Goals",
                    "kind": "short",
                    "prompt": "Explain the goal.",
                    "rubric": ["One", "Two", "Three"],
                    "answer": "A stated goal.",
                    "pages": [{"document_id": 1, "page_number": 1}],
                }
            },
            {"id": 1, "name": "Goals"},
            [{"document_id": 1, "page_number": 1, "filename": "notes.pdf", "body": "Goal"}],
            "mcq",
        )
        self.assertIsNone(question)


if __name__ == "__main__":
    unittest.main()
