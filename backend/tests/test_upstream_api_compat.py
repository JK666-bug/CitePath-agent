"""Cross-version contracts that must survive the upstream feature merge."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from agent import qa


class UpstreamApiCompatibilityTest(unittest.TestCase):
    def setUp(self):
        main.app.dependency_overrides[main.current_user] = lambda: {"id": 11, "username": "student"}
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_practice_keeps_threshold_and_preferences_separate(self):
        with patch("main.start_practice", return_value={"id": 9}) as start:
            result = self.client.post("/api/courses/2/chapters/3/practice", json={
                "passing_threshold": 0.9, "difficulty": "hard", "similar_to_cases": True,
                "case_document_ids": [17], "requirements": "Use worked examples"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(start.call_args.args, (11, 2, 3))
        self.assertEqual(start.call_args.kwargs["passing_threshold"], 0.9)
        self.assertEqual(start.call_args.kwargs["prefs"]["case_document_ids"], [17])
        self.assertEqual(start.call_args.kwargs["prefs"]["difficulty"], "hard")

    def test_plan_selection_keeps_profile_and_optimistic_version_guard(self):
        with patch("main.generate_plan", return_value={"status": "ready"}) as generate:
            result = self.client.post("/api/courses/2/plan", json={
                "start": "2026-11-18", "end": "2026-12-18", "document_ids": [6],
                "profile": {"goal": "Exam"}, "update_materials": True, "expected_version": 3})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(generate.call_args.kwargs, {"profile": {"goal": "Exam"},
            "update_materials": True, "expected_version": 3, "document_ids": [6]})

    def test_missing_qa_selection_and_explicit_empty_selection_are_distinct(self):
        for payload, expected in (({}, None), ({"document_ids": []}, []), ({"document_ids": [6]}, [6])):
            with self.subTest(payload=payload), patch("main.answer_question", return_value={"answer": "ok"}) as answer:
                result = self.client.post("/api/courses/2/questions", json={"question": "Explain trees", **payload})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(answer.call_args.kwargs["document_ids"], expected)

    def test_qa_tab_and_web_preference_are_forwarded(self):
        with patch("main.answer_question", return_value={"answer": "ok"}) as answer:
            result = self.client.post("/api/courses/2/questions", json={
                "question": "Explain trees", "document_ids": [6], "tab_id": "tab-1", "include_web": True})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(answer.call_args.kwargs, {"document_ids": [6], "tab_id": "tab-1", "include_web": True})

    def test_evaluation_context_still_requires_dedicated_account(self):
        with patch("main.answer_question") as answer:
            result = self.client.post("/api/courses/2/questions", json={"question": "Explain trees",
                "evaluation_context": {"evaluation_id": "eval", "system": "full", "item_id": "one"}})
        self.assertEqual(result.status_code, 403)
        answer.assert_not_called()

    def test_selected_qa_materials_exclude_archived_and_sample_answers(self):
        ready = {"ingest_status": "complete", "usable_page_count": 2}
        course = {"documents": [{**ready, "id": 6}, {**ready, "id": 7, "is_active": False},
            {**ready, "id": 8, "kind": "exam_case"}, {**ready, "id": 9, "kind": "case_answer"}]}
        self.assertEqual(qa._selected_document_ids(course, None), [6])
        for identifier in (7, 8, 9):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                qa._selected_document_ids(course, [identifier])

    def test_web_resynthesis_uses_imported_json_helper(self):
        with patch("agent.qa.invoke_json", return_value={"answer": "from web"}) as invoke:
            answer = qa._resynthesize_with_web("trees", [], [], {}, followup=True)
        self.assertEqual(answer, {"answer": "from web"})
        invoke.assert_called_once()


if __name__ == "__main__":
    unittest.main()
