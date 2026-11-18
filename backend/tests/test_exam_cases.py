import unittest
from unittest.mock import patch

from agent.exam import _chapter_prompt, _exam_case_answers
from agent.practice import (
    _case_pages_for_prefs,
    _preference_block,
    _prompt,
    normalize_practice_prefs,
)
from db.exam_cases import ANSWER_MODES


class ExamCaseModesTest(unittest.TestCase):
    def test_answer_modes_are_exact(self):
        self.assertEqual(ANSWER_MODES, {"none", "in_case", "file"})


class PracticePrefsTest(unittest.TestCase):
    @patch("agent.practice.list_exam_cases")
    def test_empty_prefs_stay_empty(self, list_cases):
        list_cases.return_value = [
            {
                "id": 9,
                "ingest_status": "complete",
                "usable_page_count": 3,
            }
        ]
        self.assertEqual(normalize_practice_prefs(None, 1, 2), {})
        self.assertEqual(normalize_practice_prefs({}, 1, 2), {})
        self.assertEqual(
            normalize_practice_prefs(
                {
                    "requirements": "  ",
                    "difficulty": "default",
                    "similar_to_cases": False,
                    "preferred_kind": "any",
                    "question_count": None,
                    "case_document_ids": [],
                },
                1,
                2,
            ),
            {},
        )
        list_cases.assert_called()

    @patch("agent.practice.list_exam_cases")
    def test_similar_without_ids_uses_all_ready_cases(self, list_cases):
        list_cases.return_value = [
            {"id": 3, "ingest_status": "complete", "usable_page_count": 2},
            {"id": 4, "ingest_status": "pending", "usable_page_count": 2},
            {"id": 5, "ingest_status": "complete", "usable_page_count": 0},
            {"id": 7, "ingest_status": "complete", "usable_page_count": 1},
        ]
        prefs = normalize_practice_prefs(
            {"similar_to_cases": True, "difficulty": "hard"},
            1,
            2,
        )
        self.assertTrue(prefs["similar_to_cases"])
        self.assertEqual(prefs["difficulty"], "hard")
        self.assertEqual(prefs["case_document_ids"], [3, 7])

    @patch("agent.practice.list_exam_cases")
    def test_selected_case_ids_force_similar(self, list_cases):
        list_cases.return_value = [
            {"id": 3, "ingest_status": "complete", "usable_page_count": 2},
            {"id": 8, "ingest_status": "complete", "usable_page_count": 2},
        ]
        prefs = normalize_practice_prefs(
            {"case_document_ids": [8, 99, 8], "similar_to_cases": False},
            1,
            2,
        )
        self.assertTrue(prefs["similar_to_cases"])
        self.assertEqual(prefs["case_document_ids"], [8])

    def test_preference_block_and_prompt_defaults(self):
        pages = [
            {
                "document_id": 1,
                "filename": "lecture.pdf",
                "page_number": 1,
                "body": "Goals matter.",
            }
        ]
        concept = {"id": 1, "name": "Goals"}
        plain = _prompt(concept, pages, "mcq", None, {}, None)
        self.assertIn("Requested kind: mcq", plain)
        self.assertNotIn("Student preferences", plain)
        self.assertNotIn("Exam-case sample pages", plain)

        guided = _preference_block(
            {
                "requirements": "Focus on definitions",
                "difficulty": "medium",
                "preferred_kind": "short",
                "question_count": 8,
                "similar_to_cases": True,
            }
        )
        self.assertIn("Difficulty: medium", guided)
        self.assertIn("about 8 questions", guided)
        self.assertIn("Match the style of the exam-case samples", guided)

    @patch("agent.practice.load_case_pages")
    def test_case_pages_only_when_similar(self, load_pages):
        load_pages.return_value = [
            {
                "document_id": 3,
                "filename": "case.pdf",
                "page_number": 1,
                "body": "Sample Q1",
            }
        ]
        self.assertEqual(_case_pages_for_prefs(2, {}), [])
        self.assertEqual(
            _case_pages_for_prefs(2, {"similar_to_cases": True, "case_document_ids": []}),
            [],
        )
        pages = _case_pages_for_prefs(
            2,
            {"similar_to_cases": True, "case_document_ids": [3]},
        )
        self.assertEqual(len(pages), 1)
        load_pages.assert_called_with(2, [3], include_answers=False)

        content = _prompt(
            {"id": 1, "name": "Goals"},
            [
                {
                    "document_id": 1,
                    "filename": "lecture.pdf",
                    "page_number": 1,
                    "body": "Goals matter.",
                }
            ],
            "short",
            None,
            {
                "difficulty": "hard",
                "similar_to_cases": True,
                "case_document_ids": [3],
            },
            2,
        )
        self.assertIn("Difficulty: hard", content)
        self.assertIn("case.pdf", content)


class ExamStylePromptTest(unittest.TestCase):
    @patch("agent.exam._exam_case_pages")
    def test_chapter_prompt_without_cases_matches_baseline(self, case_pages):
        case_pages.return_value = []
        chapter = {
            "course_id": 2,
            "title": "Intro",
            "concepts": [{"name": "Goals"}],
            "pages": [
                {
                    "document_id": 1,
                    "filename": "lecture.pdf",
                    "page_number": 1,
                    "body": "Goals matter.",
                }
            ],
        }
        prompt = _chapter_prompt(chapter)
        self.assertIn("Chapter: Intro", prompt)
        self.assertIn("lecture.pdf", prompt)
        self.assertNotIn("Exam-case sample pages", prompt)

    @patch("agent.exam._exam_case_pages")
    def test_chapter_prompt_includes_case_filenames(self, case_pages):
        case_pages.return_value = [
            {
                "document_id": 9,
                "filename": "midterm-sample.pdf",
                "page_number": 1,
                "body": "Q1. Define goal.",
            }
        ]
        chapter = {
            "course_id": 2,
            "title": "Intro",
            "concepts": [{"name": "Goals"}],
            "pages": [
                {
                    "document_id": 1,
                    "filename": "lecture.pdf",
                    "page_number": 1,
                    "body": "Goals matter.",
                }
            ],
        }
        prompt = _chapter_prompt(chapter)
        self.assertIn("Exam-case sample pages for style only:", prompt)
        self.assertIn("midterm-sample.pdf", prompt)

    @patch("db.exam_cases.load_case_pages")
    def test_exam_case_answers_filters_answer_material(self, load_pages):
        load_pages.return_value = [
            {
                "document_id": 9,
                "filename": "case.pdf",
                "kind": "exam_case",
                "answer_mode": "none",
                "page_number": 1,
                "body": "Question only",
            },
            {
                "document_id": 9,
                "filename": "case-with-answers.pdf",
                "kind": "exam_case",
                "answer_mode": "in_case",
                "page_number": 1,
                "body": "Answer: goals",
            },
            {
                "document_id": 10,
                "filename": "answers.pdf",
                "kind": "case_answer",
                "answer_mode": None,
                "page_number": 1,
                "body": "Key points",
            },
        ]
        text = _exam_case_answers(2)
        self.assertIn("case-with-answers.pdf", text)
        self.assertIn("answers.pdf", text)
        self.assertNotIn("Question only", text)


if __name__ == "__main__":
    unittest.main()
