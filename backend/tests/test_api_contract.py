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
            start.assert_called_once_with(11, 2, 3, 0.8)

    def test_configured_threshold_and_invalid_requests(self):
        with patch("main.start_practice", return_value={"id": 9}) as start:
            response = self.client.post("/api/courses/2/chapters/3/practice", json={"passing_threshold": 0.9})
            self.assertEqual(response.status_code, 200)
            start.assert_called_once_with(11, 2, 3, 0.9)
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


if __name__ == "__main__":
    unittest.main()
