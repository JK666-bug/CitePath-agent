import unittest
from unittest.mock import patch

from agent.web import _focus, _public_http, _result_url

from agent.qa import (
    answer_question,
    _accepts_web,
    _web_followup_topic,
    _asks_about_self,
    _is_greeting,
    _lecture_supported,
    _offers_web,
    _rejects_web,
    _with_web_ask,
    memory_messages,
)
from agent.skills import load_skill
from db.study_status import chapter_report, concept_report, mastery_label, wrong_report


class SkillLoadTest(unittest.TestCase):
    def test_qa_skill_lists_tools(self):
        body = load_skill("qa")
        self.assertNotIn("name: qa", body)
        self.assertIn("latest 10 turns", body)
        self.assertIn("whether they want a public web search", body)
        self.assertIn("web-only", body)
        self.assertIn("Web chip is on", body)
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

    def test_web_ask_is_appended_when_missing(self):
        text = _with_web_ask("No panda in the notes.", include_web=False)
        self.assertIn("search the public web", text)
        self.assertIn("automatically", text)
        already = _with_web_ask(
            "Shall I search the web for this?",
            include_web=False,
        )
        self.assertEqual(already, "Shall I search the web for this?")
        enabled = _with_web_ask("No panda in the notes.", include_web=True)
        self.assertEqual(enabled, "No panda in the notes.")

    def test_yes_followup_accepts_web_offer(self):
        self.assertTrue(_accepts_web("可以"))
        self.assertTrue(_accepts_web("好的"))
        self.assertTrue(_accepts_web("yes"))
        self.assertFalse(_accepts_web("不可以"))
        self.assertTrue(_rejects_web("不用了"))
        self.assertTrue(
            _offers_web(
                "需要我帮你联网查一下神经网络训练（反向传播、激活函数）的公开资料吗？"
            )
        )
        self.assertTrue(
            _offers_web(
                "需要我帮你上网查一份更系统的神经网络入门讲解吗？"
            )
        )

    def test_greetings_are_not_course_questions(self):
        self.assertTrue(_is_greeting("你好"))
        self.assertTrue(_is_greeting("hello"))
        self.assertTrue(_is_greeting("谢谢"))
        self.assertTrue(_is_greeting("好的"))
        self.assertFalse(_is_greeting("When is recovery funding released?"))
        self.assertFalse(_is_greeting("你好，珊瑚白化是什么"))

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

    def test_course_framing_with_web_offer_is_still_supported(self):
        from agent.qa import _declines

        answer = (
            "In the course's framing, machine learning is used as predictive "
            "analytics: the model learns from labeled fraud examples (L01, p.45). "
            "If you want a general textbook definition, I can search the web."
        )
        self.assertFalse(_declines(answer))
        self.assertIn("whether they want a public web search", load_skill("qa"))
        self.assertIn("formal textbook definition", load_skill("qa"))

    def test_web_followup_is_web_only(self):
        body = load_skill("qa")
        self.assertIn("web-only", body)
        self.assertIn("Do **not** restate lecture", body)
        from agent.qa import EMPTY_WEB, WEB_FOLLOWUP_NOTE

        self.assertIn("没有返回可用", EMPTY_WEB)
        self.assertIn("Do not call search_notes", WEB_FOLLOWUP_NOTE)


class CourseRoutingTest(unittest.TestCase):
    def test_acknowledgement_does_not_web_search_private_course_question(self):
        previous = [{"question": "我的学习情况", "answer": "需要我帮你联网查一下吗？"}]
        with patch("agent.qa.recent_turns", return_value=previous):
            self.assertIsNone(_web_followup_topic(3, 7, "好的", "tab-1"))

    def test_course_count_uses_agent_without_selected_pdfs(self):
        with (
            patch("agent.qa.get_course", return_value={"id": 7, "name": "Test", "documents": []}),
            patch("agent.qa._web_followup_topic", return_value=None),
            patch("agent.qa._choose_and_answer", return_value=([], {"answer": "You have 2 courses."}, True, [], False, True)) as agent,
            patch("agent.qa._store", return_value={"ok": True}) as store,
        ):
            self.assertEqual(answer_question(3, 7, "我有几门课", []), {"ok": True})
        self.assertEqual(agent.call_args.args[0], [])
        self.assertEqual(store.call_args.args[4], [])
        self.assertEqual(store.call_args.args[7], "course")

    def test_course_answer_does_not_cite_selected_lecture(self):
        page = {"document_id": 11, "page_number": 1, "filename": "lecture.pdf"}
        with (
            patch("agent.qa.get_course", return_value={"id": 7, "name": "Test", "documents": []}),
            patch("agent.qa._web_followup_topic", return_value=None),
            patch("agent.qa._choose_and_answer", return_value=([page], {"answer": "You have 2 courses.", "cited_pages": [page]}, True, [], False, True)),
            patch("agent.qa._store", return_value={"ok": True}) as store,
        ):
            answer_question(3, 7, "我有几门课", [11])
        self.assertEqual(store.call_args.args[4], [])
        self.assertEqual(store.call_args.args[7], "course")

    def test_learning_progress_uses_study_tools_without_selected_pdfs(self):
        with (
            patch("agent.qa.get_course", return_value={"id": 7, "name": "Test", "documents": []}),
            patch("agent.qa._web_followup_topic", return_value=None),
            patch("agent.qa._choose_and_answer", return_value=([], {"answer": "Two concepts mastered."}, True, [], False, False)) as agent,
            patch("agent.qa._store", return_value={"ok": True}) as store,
        ):
            answer_question(3, 7, "我的学习情况", [])
        self.assertEqual(agent.call_args.args[0], [])
        self.assertEqual(store.call_args.args[4], [])
        self.assertEqual(store.call_args.args[7], "study")


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

    def test_focus_strips_definition_wrappers(self):
        self.assertEqual(_focus("什么是随机森林"), "随机森林")
        self.assertEqual(_focus("what is random forest"), "random forest")
