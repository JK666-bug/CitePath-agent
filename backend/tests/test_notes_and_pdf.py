import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from agent.notes import _render_pdf, _safe_name, _valid
from db import pdf_store


class NotesValidationTest(unittest.TestCase):
    def test_rejects_empty_notes_payload(self):
        self.assertFalse(_valid(None))
        self.assertFalse(_valid({}))
        self.assertFalse(_valid({"title": "X", "sections": []}))
        self.assertTrue(
            _valid(
                {
                    "title": "Goals",
                    "sections": [
                        {"heading": "One", "bullets": ["a", "b"], "note": ""},
                    ],
                }
            )
        )

    def test_render_pdf_returns_bytes(self):
        cheat_payload = {
            "title": "Algorithms cheat sheet",
            "subtitle": "Week 1",
            "layout": {"columns": 2, "density": "compact"},
            "sections": [
                {
                    "heading": "Trees",
                    "bullets": [
                        "Binary trees have at most two children",
                        "Heap is a complete binary tree",
                        "BFS uses a queue",
                    ],
                    "note": "Useful for exams",
                },
                {
                    "heading": "Graphs",
                    "bullets": ["DFS uses a stack or recursion", "Dijkstra needs non-negative weights"],
                    "note": "",
                },
            ],
        }
        data = _render_pdf(
            "Algorithms",
            cheat_payload,
            "cheatsheet",
            "a5",
            max_pages=1,
            type_size="tiny",
        )
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 200)
        double = _render_pdf(
            "Algorithms",
            cheat_payload,
            "cheatsheet",
            "a5",
            max_pages=2,
            type_size="small",
        )
        self.assertTrue(double.startswith(b"%PDF"))
        with fitz.open(stream=data, filetype="pdf") as single_doc:
            self.assertEqual(single_doc.page_count, 1)
        with fitz.open(stream=double, filetype="pdf") as double_doc:
            self.assertEqual(double_doc.page_count, 2)
        notes = _render_pdf(
            "Algorithms",
            {
                "title": "Study notes",
                "subtitle": "Week 1",
                "sections": [
                    {
                        "heading": "Trees",
                        "bullets": ["Binary trees have at most two children"],
                        "note": "",
                    }
                ],
            },
            "notes",
            "a4",
        )
        self.assertTrue(notes.startswith(b"%PDF"))

    def test_safe_name(self):
        self.assertEqual(_safe_name("My Notes!"), "My-Notes")
        self.assertEqual(_safe_name(""), "course-notes")


class PdfStoreTest(unittest.TestCase):
    def test_save_read_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(pdf_store, "PDF_ROOT", root):
                self.assertFalse(pdf_store.has_pdf(7, 3))
                pdf_store.save_pdf(7, 3, b"%PDF-1.4 sample")
                self.assertTrue(pdf_store.has_pdf(7, 3))
                self.assertEqual(pdf_store.read_pdf_bytes(7, 3), b"%PDF-1.4 sample")
                pdf_store.delete_pdf(7, 3)
                self.assertFalse(pdf_store.has_pdf(7, 3))
                self.assertIsNone(pdf_store.read_pdf_bytes(7, 3))


class QaTabTitleTest(unittest.TestCase):
    def test_title_from_question(self):
        from db.qa import _title_from_question

        self.assertEqual(_title_from_question(""), "New chat")
        self.assertEqual(
            _title_from_question("  What is a tree?  "),
            "What is a tree?",
        )


if __name__ == "__main__":
    unittest.main()
