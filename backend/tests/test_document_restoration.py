import hashlib
import os
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from db import courses, document_files, uploads


PDF = b"%PDF-1.7\nimmutable original lecture\n%%EOF"
PAGES = [{"page_number": 7, "body": "Hash functions map keys to buckets.", "usable": 1}]


class DocumentRestorationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {"PDF_STORAGE_DIR": temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.path = document_files.save_original_pdf(42, PDF)
        self.row = {"id": 42, "filename": "lecture.pdf", "content_hash": hashlib.sha256(PDF).hexdigest(),
                    "is_active": 0, "ingest_status": "complete", "page_count": 1, "usable_page_count": 1}
        for name, value in (("ensure_document_numbers", None), ("document_ingestion_lock", lambda _: nullcontext()),
                            ("_hash_row", lambda *_: self.row), ("_load_pages", lambda *_: PAGES)):
            mock = patch.object(uploads, name, side_effect=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_same_hash_reupload_restores_same_id_only_after_index_flush(self):
        events = []

        def status(document_id, state, error=None):
            self.assertEqual(document_id, 42)
            self.assertFalse(self.row["is_active"])
            self.row["ingest_status"] = state
            events.append(state)

        def sync(document_id, pages):
            self.assertEqual(self.path.read_bytes(), PDF)
            self.assertEqual(pages, PAGES)
            self.assertFalse(self.row["is_active"])
            events.append("vectors flushed")
            return 3

        def activate(course_id, document_id):
            self.assertEqual((course_id, document_id), (5, 42))
            self.assertEqual(self.row["ingest_status"], "complete")
            events.append("active")
            self.row["is_active"] = 1

        with patch.object(uploads, "_set_ingestion_status", side_effect=status), patch.object(
            uploads, "sync_pages", side_effect=sync
        ), patch.object(uploads, "_activate_document", side_effect=activate):
            result = uploads.existing_upload(5, self.row["content_hash"], pdf_data=PDF)
        self.assertEqual(events, ["pending", "vectors flushed", "complete", "active"])
        self.assertEqual(result["document_id"], 42)
        self.assertTrue(result["restored"])
        self.assertEqual(self.path.read_bytes(), PDF)

    def test_wrong_pdf_cannot_replace_original_identity_or_bytes(self):
        with patch.object(uploads, "_store_original_pdf") as store, patch.object(uploads, "sync_pages") as sync, \
                patch.object(uploads, "_activate_document") as activate:
            with self.assertRaisesRegex(ValueError, "original hash"):
                uploads._restore_upload(5, self.row, b"different PDF")
        store.assert_not_called()
        sync.assert_not_called()
        activate.assert_not_called()
        self.assertEqual(self.path.read_bytes(), PDF)
        self.assertFalse(self.row["is_active"])

    def test_failed_reindex_remains_archived_and_retains_original(self):
        states = []
        with patch.object(uploads, "_set_ingestion_status", side_effect=lambda _, state, error=None: states.append(state)), \
                patch.object(uploads, "sync_pages", side_effect=ConnectionError("Milvus unavailable")), \
                patch.object(uploads, "_activate_document") as activate:
            with self.assertRaisesRegex(RuntimeError, "vector indexing failed"):
                uploads._restore_upload(5, self.row)
        self.assertEqual(states, ["pending", "failed"])
        activate.assert_not_called()
        self.assertFalse(self.row["is_active"])
        self.assertEqual(self.path.read_bytes(), PDF)

    def test_missing_original_or_legacy_hash_is_not_silently_reassigned(self):
        self.path.unlink()
        with patch.object(uploads, "sync_pages") as sync:
            with self.assertRaisesRegex(ValueError, "exact same PDF"):
                uploads._restore_upload(5, self.row)
            self.row["content_hash"] = None
            with self.assertRaisesRegex(ValueError, "cannot be reassigned"):
                uploads._restore_upload(5, self.row, PDF)
        sync.assert_not_called()

    def test_removed_source_blocks_new_generation_without_vector_access(self):
        with patch.object(uploads, "has_segments") as vector:
            with self.assertRaisesRegex(ValueError, "Restore it"):
                uploads.require_ingested_documents([self.row])
        vector.assert_not_called()


class DocumentOwnershipAndArchiveTest(unittest.TestCase):
    def test_archived_sources_are_retained_in_history_but_not_new_answer_memory(self):
        from db import qa
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [[
            {"question": "Recent archived note", "answer": "Archived text", "cited_pages": '[{"document_id":42}]'},
            {"question": "Active note", "answer": "Current text", "cited_pages": '[{"document_id":67}]'},
            {"question": "Chat", "answer": "Hello", "cited_pages": None},
        ], [{"id": 67}]]
        with patch.object(qa, "connect", return_value=connection):
            memory = qa.recent_turns(11, 5)
        self.assertEqual([row["question"] for row in memory], ["Chat", "Active note"])
        self.assertFalse(any("DELETE" in call.args[0] for call in cursor.execute.call_args_list))

    def test_inventory_foreign_course_does_not_read_documents_or_files(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        with patch.object(courses, "ensure_document_numbers"), patch.object(courses, "connect", return_value=connection), \
                patch.object(courses, "original_pdf_path") as path:
            with self.assertRaises(LookupError):
                courses.document_inventory(11, 5)
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertEqual(cursor.execute.call_args.args[1], (5, 11))
        path.assert_not_called()

    def test_restore_foreign_document_never_reads_hash_or_indexes(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        with patch.object(uploads, "ensure_document_numbers"), patch.object(uploads, "connect", return_value=connection), \
                patch.object(uploads, "_hash_row") as hashed, patch.object(uploads, "_restore_upload") as restore:
            with self.assertRaises(LookupError):
                uploads.restore_document(11, 5, 42)
        self.assertEqual(cursor.execute.call_args.args[1], (42, 5, 11))
        hashed.assert_not_called()
        restore.assert_not_called()

    def test_archive_retains_relational_history_and_only_renumbers_active_material(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [{"course_id": 5}, {"id": 5}]
        cursor.fetchall.return_value = [{"id": 67, "position": 2}]
        with patch.object(courses, "connect", return_value=connection):
            result = courses._archive_document(42)
        statements = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
        self.assertTrue(result["archived"])
        self.assertTrue(any("is_active = 0" in sql and "position = NULL" in sql for sql in statements))
        self.assertTrue(any("is_active = 1" in sql and "FOR UPDATE" in sql for sql in statements))
        self.assertFalse(any("DELETE" in sql for sql in statements))
        self.assertEqual(cursor.execute.call_args.args[1], (1, 67, 5))
        connection.commit.assert_called_once()

    def test_activation_assigns_new_display_position_without_changing_document_id(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [{"id": 5}, {"is_active": 0}, {"n": 3}]
        with patch.object(uploads, "connect", return_value=connection):
            uploads._activate_document(5, 42)
        self.assertEqual(cursor.execute.call_args.args[1], (3, 42, 5))
        self.assertIn("removed_at = NULL", cursor.execute.call_args.args[0])
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
