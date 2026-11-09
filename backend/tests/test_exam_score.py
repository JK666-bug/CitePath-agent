import unittest

from agent.exam import questions_from_reply
from grading.score import choice_correct, exam_pass, percent, points_pass


class ExamQuestionTest(unittest.TestCase):
    def test_keeps_one_choice_and_one_short_question_per_concept(self):
        chapter = {
            "concepts": [{"id": 3, "name": "Binary tree"}],
            "pages": [],
        }
        questions = questions_from_reply(
            {
                "questions": [
                    {
                        "concept": "Binary tree",
                        "kind": "mcq",
                        "prompt": "Which structure has one root?",
                        "options": ["A graph", "A tree", "A queue", "A heap"],
                        "answer": "B",
                        "pages": [{"document_id": 1, "page_number": 2}],
                    },
                    {
                        "concept": "Binary tree",
                        "kind": "mcq",
                        "prompt": "Ignore this duplicate with letter-only choices.",
                        "options": ["A", "B", "C", "D"],
                        "answer": "A",
                        "pages": [{"document_id": 1, "page_number": 2}],
                    },
                    {
                        "concept": "Binary tree",
                        "kind": "short",
                        "prompt": "Describe a binary tree.",
                        "rubric": ["One root", "At most two children", "Connected nodes"],
                        "answer": "A binary tree has one root and at most two children.",
                        "pages": [{"document_id": 1, "page_number": 2}, {"document_id": 9, "page_number": 9}],
                    },
                ]
            },
            {
                **chapter,
                "pages": [
                    {
                        "document_id": 1,
                        "page_number": 2,
                        "filename": "notes.pdf",
                        "position": 1,
                        "body": "A tree has one root.",
                    }
                ],
            },
        )
        self.assertEqual([item["kind"] for item in questions], ["mcq", "short"])
        self.assertEqual(
            questions[0]["options"],
            ["A graph", "A tree", "A queue", "A heap"],
        )
        self.assertEqual(questions[1]["sources"][0]["position"], 1)

    def test_rejects_a_chapter_missing_a_concept_question(self):
        questions = questions_from_reply(
            {"questions": []},
            {
                "concepts": [{"id": 1, "name": "Tree"}],
                "pages": [{"document_id": 1, "page_number": 1, "filename": "notes.pdf", "body": "Tree"}],
            },
        )
        self.assertEqual(questions, [])


class ExamScoreTest(unittest.TestCase):
    def test_choice_matches_the_letter(self):
        self.assertTrue(choice_correct("b", "B"))
        self.assertFalse(choice_correct("A", "B"))
        self.assertFalse(choice_correct("", "A"))

    def test_short_answer_needs_eighty_percent_of_the_points(self):
        self.assertTrue(points_pass(4, 5))
        self.assertFalse(points_pass(3, 4))

    def test_exam_needs_eighty_percent_of_the_questions(self):
        self.assertTrue(exam_pass(4, 5))
        self.assertFalse(exam_pass(3, 5))
        self.assertEqual(percent(3, 4), 75)
