import unittest

from agent.web import _public_http, _result_url

from agent.qa import _asks_about_self, _is_chat, _lecture_supported, memory_messages
from agent.skills import load_skill
from db.study_status import chapter_report, concept_report, mastery_label, wrong_report


class SkillLoadTest(unittest.TestCase):
    def test_qa_skill_chooses_one_tool(self):
        body = load_skill("qa")
        self.assertNotIn("name: qa", body)
        self.assertIn("latest 10 turns", body)
        for name in (
            "review_status",
            "concept_mastery",
            "chapter_mastery",
            "wrong_answers",
            "account_info",
            "search_notes",
            "search_web",
        ):
            self.assertIn(name, body)

    def test_memory_keeps_the_latest_ten_turns(self):
        turns = [
            {"question": f"Question {index}", "answer": "x" * 600}
            for index in range(12)
        ]
        messages = memory_messages(turns)
        self.assertEqual(len(messages), 20)
        self.assertEqual(messages[0].content, "Question 2")
        self.assertEqual(len(messages[1].content), 500)

    def test_a_disclaimer_is_not_a_lecture_answer(self):
        pages = [{"document_id": 6, "page_number": 1, "filename": "notes.pdf"}]
        parsed = {
            "supported": True,
            "answer": "The lecture notes do not contain specific information about the iPhone.",
            "cited_pages": [{"document_id": 6, "page_number": 1}],
        }
        self.assertFalse(_lecture_supported(parsed, pages))
        self.assertTrue(_asks_about_self("我名字是什么"))
        self.assertFalse(_asks_about_self("what is iPhone"))
        self.assertTrue(_is_chat("我19岁了"))
        self.assertFalse(_is_chat("我名字是什么"))
        self.assertFalse(_is_chat("what is iPhone"))
        self.assertFalse(_is_chat("二叉树"))


class StudyReportTest(unittest.TestCase):
    def test_reports_keep_a_named_chapter(self):
        record = {
            "chapters": [
                {
                    "title": "Trees",
                    "concepts": [{"name": "Heap", "status": 2, "label": "Mastered"}],
                    "mastered_concepts": 1,
                    "total_concepts": 1,
                    "finished_rounds": 1,
                    "practice_open": False,
                    "practice_correct": 2,
                    "practice_wrong": 1,
                }
            ],
            "exams": {"Trees": {"taken": 1, "passed": 0}},
            "practice_wrongs": [
                {
                    "chapter": "Trees",
                    "concept": "Heap",
                    "prompt": "What is a heap?",
                    "response": "A list",
                    "answer": "A tree",
                    "explanation": "The page says tree.",
                }
            ],
            "exam_wrongs": [],
        }
        concepts = concept_report(record, "Trees")
        self.assertEqual(concepts["matches"][0]["concepts"][0]["status"], 2)
        chapters = chapter_report(record, "")
        self.assertTrue(chapters["matches"][0]["mastered"])
        wrong = wrong_report(record, "Sorting")
        self.assertIn("Sorting", wrong["note"])
        self.assertEqual(mastery_label(0, 1), (1, "One correct, not yet mastered"))


class WebLinkTest(unittest.TestCase):
    def test_web_results_reject_local_addresses(self):
        self.assertFalse(_public_http("http://127.0.0.1/secret"))
        self.assertFalse(_public_http("javascript:alert(1)"))
        self.assertEqual(
            _result_url("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa"),
            "https://example.com/a",
        )
