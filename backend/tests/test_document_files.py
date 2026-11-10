import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from db import document_files, uploads


PDF = b"%PDF-1.7\noriginal source bytes\n%%EOF"


class OriginalPdfTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        setting = patch.dict(os.environ, {"PDF_STORAGE_DIR": self.directory.name})
        setting.start()
        self.addCleanup(setting.stop)

    def test_saves_exact_bytes_and_reopens_with_document_id(self):
        saved = document_files.save_original_pdf(7, PDF)
        self.assertEqual(saved.name, "7.pdf")
        self.assertEqual(saved.parent, Path(self.directory.name).resolve())
        self.assertEqual(document_files.original_pdf_path(7).read_bytes(), PDF)
        self.assertEqual([path.resolve() for path in Path(self.directory.name).iterdir()], [saved])

    def test_ids_cannot_escape_storage_or_use_arbitrary_filenames(self):
        for document_id in ["../secret", "7", -1, 0, True, 1.2]:
            with self.subTest(document_id=document_id), self.assertRaises(ValueError):
                document_files.original_pdf_path(document_id)

    def test_failed_atomic_replace_keeps_original_and_removes_temporary(self):
        saved = document_files.save_original_pdf(7, PDF)
        with patch.object(document_files.os, "replace", side_effect=OSError("storage unavailable")):
            with self.assertRaises(OSError):
                document_files.save_original_pdf(7, b"replacement")
        self.assertEqual(saved.read_bytes(), PDF)
        self.assertEqual([path.resolve() for path in Path(self.directory.name).iterdir()], [saved])

    def test_delete_removes_only_the_requested_file(self):
        document_files.save_original_pdf(7, PDF)
        document_files.save_original_pdf(8, PDF)
        document_files.delete_original_pdf(7)
        document_files.delete_original_pdf(7)
        self.assertIsNone(document_files.original_pdf_path(7))
        self.assertEqual(document_files.original_pdf_path(8).read_bytes(), PDF)

    def test_missing_original_returns_none_without_creating_storage(self):
        directory = Path(self.directory.name) / "not-yet-created"
        with patch.dict(os.environ, {"PDF_STORAGE_DIR": str(directory)}):
            self.assertIsNone(document_files.original_pdf_path(7))
        self.assertFalse(directory.exists())


class UploadOriginalTest(unittest.TestCase):
    def test_original_is_retained_before_vector_failure(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"n": 1}
        cursor.lastrowid = 7
        events = []
        connection.commit.side_effect = lambda: events.append("pages committed")

        def original(document_id, data):
            self.assertEqual(events, ["pages committed"])
            self.assertEqual((document_id, data), (7, PDF))
            events.append("original saved")

        def index(document_id, pages):
            self.assertEqual(events, ["pages committed", "original saved"])
            raise RuntimeError("vector unavailable")

        with patch.object(uploads, "ensure_document_numbers"), patch.object(
            uploads, "connect", return_value=connection
        ), patch.object(uploads, "save_original_pdf", side_effect=original), patch.object(
            uploads, "_sync_document", side_effect=index
        ):
            with self.assertRaisesRegex(RuntimeError, "vector unavailable"):
                uploads.save_document(3, "lecture.pdf", [{"page_number": 1, "body": "Text", "usable": 1}], "hash", pdf_data=PDF)
        self.assertEqual(events, ["pages committed", "original saved"])

    def test_reupload_fills_missing_original_without_reindexing_ready_document(self):
        row = {"id": 7, "filename": "lecture.pdf", "page_count": 1, "usable_page_count": 1, "ingest_status": "complete"}
        with patch.object(uploads, "ensure_document_numbers"), patch.object(
            uploads, "_hash_row", return_value=row
        ), patch.object(uploads, "save_original_pdf") as original, patch.object(
            uploads, "has_segments", return_value=True
        ), patch.object(uploads, "_sync_document") as index:
            result = uploads.existing_upload(3, "hash", pdf_data=PDF)
        original.assert_called_once_with(7, PDF)
        index.assert_not_called()
        self.assertEqual(result["document_id"], 7)
        self.assertTrue(result["duplicate"])

    def test_storage_failure_marks_document_failed_and_blocks_indexing(self):
        with patch.object(uploads, "save_original_pdf", side_effect=OSError("disk full")), patch.object(
            uploads, "_set_ingestion_status"
        ) as status:
            with self.assertRaisesRegex(RuntimeError, "original PDF could not be saved"):
                uploads._store_original_pdf(7, PDF)
        self.assertEqual(status.call_args.args[:2], (7, "failed"))


if __name__ == "__main__":
    unittest.main()
