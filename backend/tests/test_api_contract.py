import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class PracticeApiTest(unittest.TestCase):
    def setUp(self):
        main.app.dependency_overrides[main.current_user] = lambda: {"id": 11}
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_old_start_request_keeps_default_threshold(self):
        with patch("main.start_practice", return_value={"id": 9}) as start:
            response = self.client.post("/api/courses/2/chapters/3/practice")
            self.assertEqual(response.status_code, 200)
            start.assert_called_once_with(11, 2, 3, passing_threshold=0.8, prefs=None)

    def test_configured_threshold_and_invalid_requests(self):
        with patch("main.start_practice", return_value={"id": 9}) as start:
            response = self.client.post("/api/courses/2/chapters/3/practice", json={"passing_threshold": 0.9})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(start.call_args.args, (11, 2, 3))
            self.assertEqual(start.call_args.kwargs["passing_threshold"], 0.9)
            self.assertNotIn("passing_threshold", start.call_args.kwargs["prefs"])
        for threshold in (-1, 0, 1.1, True):
            with patch("main.start_practice") as start:
                response = self.client.post("/api/courses/2/chapters/3/practice", json={"passing_threshold": threshold})
                self.assertEqual(response.status_code, 422)
                start.assert_not_called()

    def test_draft_saves_without_grading(self):
        with patch("main.save_practice_draft", return_value={"saved": True}) as save, \
                patch("main.answer_practice") as grade:
            response = self.client.patch("/api/courses/2/practice/9/draft", json={"question_id": 4, "response": "draft"})
            self.assertEqual(response.status_code, 200)
            save.assert_called_once_with(11, 2, 9, 4, "draft")
            grade.assert_not_called()

    def test_incomplete_model_grade_returns_error_without_a_score(self):
        with patch("main.answer_practice", side_effect=RuntimeError("Grading incomplete; retry")):
            response = self.client.post("/api/courses/2/practice/9/answer", json={"question_id": 4, "response": "draft"})
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("score", response.json())

    def test_duplicate_upload_index_failure_is_actionable(self):
        with patch("main.get_course", return_value={"id": 2}), \
                patch("main.existing_upload", side_effect=RuntimeError("Indexing failed; upload again")):
            response = self.client.post("/api/courses/2/documents", files={"file": ("notes.pdf", b"pdf", "application/pdf")})
            self.assertEqual(response.status_code, 502)
            self.assertIn("upload again", response.json()["detail"])

    def test_source_pdf_requires_course_ownership(self):
        with patch("main.owns_document", return_value=False), patch("main.original_pdf_path") as path:
            response = self.client.get("/api/courses/2/documents/6/file")
            self.assertEqual(response.status_code, 404)
            path.assert_not_called()

    def test_practice_explanation_retry_returns_saved_state_without_answer_submission(self):
        saved = {"id": 9, "round_number": 2, "round_results": [{"score": 60}, {"score": 100}],
                 "report": {"passed": True, "outcome": "passed_round_2"},
                 "feedback": {"question_id": 4, "explanation_status": "failed"}}
        with patch("main.retry_practice_explanation", return_value=saved) as retry, \
                patch("main.answer_practice") as grade, patch("main.start_practice") as generate:
            response = self.client.post("/api/courses/2/practice/9/questions/4/explanation/retry")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), saved)
            retry.assert_called_once_with(11, 2, 9, 4)
            grade.assert_not_called()
            generate.assert_not_called()

    def test_explanation_retry_does_not_reveal_foreign_session(self):
        for path, helper in (("practice/9", "retry_practice_explanation"), ("exams/9", "retry_exam_explanation")):
            with self.subTest(path=path), patch("main." + helper, side_effect=LookupError("foreign session")):
                response = self.client.post(f"/api/courses/2/{path}/questions/4/explanation/retry")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("foreign", response.text)

    def test_exam_explanation_retry_preserves_official_result(self):
        record = {"id": 9, "status": "finished", "score": 80, "passed": True,
                  "report": {"score": 80, "wrong": [{"question_id": 4, "explanation_status": "ready"}]}}
        with patch("main.retry_exam_explanation", return_value=record) as retry, patch("main.submit_exam") as grade:
            response = self.client.post("/api/courses/2/exams/9/questions/4/explanation/retry")
            self.assertEqual(response.json(), record)
            retry.assert_called_once_with(11, 2, 9, 4)
            grade.assert_not_called()

    def test_source_pdf_serves_original_bytes_and_legacy_missing_is_actionable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "6.pdf"
            path.write_bytes(b"%PDF-1.7 original")
            with patch("main.owns_document", return_value=True), patch("main.original_pdf_path", return_value=path):
                response = self.client.get("/api/courses/2/documents/6/file")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, path.read_bytes())
                self.assertEqual(response.headers["content-type"], "application/pdf")
                self.assertEqual(response.headers["cache-control"], "private, no-store")
        with patch("main.owns_document", return_value=True), patch("main.original_pdf_path", return_value=None):
            response = self.client.get("/api/courses/2/documents/6/file")
            self.assertEqual(response.status_code, 404)
            self.assertIn("Upload the same PDF", response.json()["detail"])

    def test_incomplete_planning_profile_returns_questions_without_an_official_plan(self):
        result = {"status": "needs_input", "questions": [{"id": "goal", "required": True}], "plan": None}
        with patch("main.generate_plan", return_value=result) as generate:
            response = self.client.post("/api/courses/2/plan", json={
                "start": "2026-11-12", "end": "2026-12-01", "profile": {}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), result)
            self.assertEqual(generate.call_args.kwargs["profile"], {})

    def test_incremental_plan_update_has_version_guard_and_conflict_response(self):
        profile = {"goal": "Exam", "prior_knowledge": "Beginner", "daily_minutes": 60}
        body = {"start": "2026-11-12", "end": "2026-12-01", "profile": profile,
                "update_materials": True, "expected_version": 3}
        with patch("main.generate_plan", side_effect=main.PlanConflict("Plan changed; reload")) as generate:
            response = self.client.post("/api/courses/2/plan", json=body)
            self.assertEqual(response.status_code, 409)
            self.assertTrue(generate.call_args.kwargs["update_materials"])
            self.assertEqual(generate.call_args.kwargs["expected_version"], 3)
        for value in (True, 0, 1.5):
            with patch("main.generate_plan") as generate:
                response = self.client.post("/api/courses/2/plan", json={**body, "expected_version": value})
                self.assertEqual(response.status_code, 422)
                generate.assert_not_called()

    def test_plan_history_is_owned_read_only_and_missing_versions_are_404(self):
        with patch("main.get_plan_versions", return_value={"versions": [], "read_only": True}) as versions, \
                patch("main.get_plan_version", side_effect=LookupError("other user's plan")), \
                patch("main.generate_plan") as mutate:
            response = self.client.get("/api/courses/2/plan/versions")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["read_only"])
            versions.assert_called_once_with(11, 2)
            response = self.client.get("/api/courses/2/plan/versions/7")
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("other user's", response.text)
            self.assertEqual(self.client.post("/api/courses/2/plan/versions/7").status_code, 405)
            mutate.assert_not_called()

    def test_planning_requirements_pass_profile_without_starting_generation(self):
        with patch("main.planning_requirements", return_value={"status": "needs_input"}) as requirements, \
                patch("main.generate_plan") as generate:
            response = self.client.post("/api/courses/2/plan/requirements", json={"profile": {"daily_minutes": 30}})
            self.assertEqual(response.status_code, 200)
            requirements.assert_called_once_with(11, 2, {"daily_minutes": 30})
            generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
