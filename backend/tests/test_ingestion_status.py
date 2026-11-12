import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, call, patch

from db import exams, plans, uploads


PAGES = [{"page_number": 12, "body": "A binary tree has at most two children.", "usable": 1}]
DOCUMENT = {
    "id": 7,
    "filename": "lecture.pdf",
    "ingest_status": "complete",
    "ingest_error": None,
    "page_count": 1,
    "usable_page_count": 1,
}


def connection_with_cursor():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    return connection, cursor


class IngestionStorageTest(unittest.TestCase):
    def setUp(self):
        lock = patch.object(uploads, "document_ingestion_lock", side_effect=lambda _: nullcontext())
        lock.start()
        self.addCleanup(lock.stop)

    def test_publishes_complete_only_after_pages_commit_and_vector_sync(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchone.return_value = {"n": 1}
        cursor.lastrowid = 7
        events = []
        connection.commit.side_effect = lambda: events.append("pages committed")

        def synced(document_id, pages):
            self.assertEqual(events, ["pages committed", "pending"])
            self.assertEqual(document_id, 7)
            self.assertEqual(pages[0]["page_number"], 12)
            events.append("vector flushed")
            return 2

        with patch.object(uploads, "ensure_document_numbers"), patch.object(
            uploads, "connect", return_value=connection
        ), patch.object(uploads, "sync_pages", side_effect=synced), patch.object(
            uploads, "_set_ingestion_status", side_effect=lambda _, status, error=None: events.append(status)
        ):
            result = uploads.save_document(3, "lecture.pdf", PAGES, "hash")
        self.assertEqual(events, ["pages committed", "pending", "vector flushed", "complete"])
        self.assertEqual(result["ingest_status"], "complete")
        self.assertEqual(result["milvus_segments"], 2)
        connection.rollback.assert_not_called()

    def test_failed_vector_sync_remains_retriable_and_is_never_complete(self):
        with patch.object(uploads, "_set_ingestion_status") as status, patch.object(
            uploads, "sync_pages", side_effect=TimeoutError("unavailable")
        ):
            with self.assertRaisesRegex(RuntimeError, "upload the same PDF to retry"):
                uploads._sync_document(7, PAGES)
        self.assertEqual(status.call_args_list[0], call(7, "pending"))
        self.assertEqual(status.call_args_list[1].args[:2], (7, "failed"))
        self.assertIn("TimeoutError", status.call_args_list[1].args[2])
        self.assertNotIn(call(7, "complete"), status.call_args_list)

    def test_empty_vector_result_is_a_failure(self):
        with patch.object(uploads, "_set_ingestion_status") as status, patch.object(
            uploads, "sync_pages", return_value=0
        ):
            with self.assertRaisesRegex(RuntimeError, "indexing failed"):
                uploads._sync_document(7, PAGES)
        self.assertEqual(status.call_args_list[-1].args[1], "failed")

    def test_unreadable_document_is_failed_without_vector_calls(self):
        with patch.object(uploads, "_set_ingestion_status") as status, patch.object(
            uploads, "sync_pages"
        ) as sync:
            with self.assertRaisesRegex(ValueError, "no readable lecture text"):
                uploads._sync_document(7, [{"page_number": 1, "body": "", "usable": 0}])
        sync.assert_not_called()
        self.assertEqual(status.call_args_list[-1].args[1], "failed")

    def test_reupload_reindexes_failed_document_even_if_partial_vectors_exist(self):
        with patch.object(uploads, "ensure_document_numbers"), patch.object(
            uploads, "_hash_row", return_value={**DOCUMENT, "ingest_status": "failed"}
        ), patch.object(uploads, "has_segments", return_value=True) as has, patch.object(
            uploads, "_load_pages", return_value=PAGES
        ), patch.object(uploads, "_sync_document", return_value=2) as sync:
            result = uploads.existing_upload(3, "hash")
        has.assert_not_called()
        sync.assert_called_once_with(7, PAGES)
        self.assertEqual(result["document_id"], 7)
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["ingest_status"], "complete")

    def test_ready_duplicate_does_not_regenerate_or_reinsert_pages(self):
        with patch.object(uploads, "ensure_document_numbers"), patch.object(
            uploads, "_hash_row", return_value=DOCUMENT
        ), patch.object(uploads, "has_segments", return_value=True), patch.object(
            uploads, "_sync_document"
        ) as sync, patch.object(uploads, "_load_pages") as load:
            result = uploads.existing_upload(3, "hash")
        sync.assert_not_called()
        load.assert_not_called()
        self.assertTrue(result["duplicate"])

    def test_error_column_migration_keeps_existing_position_constraint(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchone.side_effect = [{"acquired": 1}, {"n": 1}, {"n": 0}, {"n": 0}, {"n": 0}]
        with patch.object(uploads, "_numbers_ready", False), patch.object(
            uploads, "connect", return_value=connection
        ):
            uploads.ensure_document_numbers()
        sql = [str(item.args[0]) for item in cursor.execute.call_args_list]
        self.assertIn("ALTER TABLE documents ADD COLUMN ingest_error TEXT NULL", sql)
        self.assertFalse(any("ADD UNIQUE KEY" in item for item in sql))


class IngestionLockTest(unittest.TestCase):
    def test_document_lock_releases_even_if_indexing_raises(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchone.return_value = {"acquired": 1}
        with patch.object(uploads, "connect", return_value=connection):
            with self.assertRaisesRegex(ValueError, "index failed"):
                with uploads.document_ingestion_lock(7):
                    raise ValueError("index failed")
        self.assertIn("GET_LOCK", cursor.execute.call_args_list[0].args[0])
        self.assertIn("RELEASE_LOCK", cursor.execute.call_args_list[-1].args[0])
        connection.close.assert_called_once()

    def test_busy_document_never_enters_indexing(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchone.return_value = {"acquired": 0}
        entered = False
        with patch.object(uploads, "connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "already being indexed"):
                with uploads.document_ingestion_lock(7):
                    entered = True
        self.assertFalse(entered)
        self.assertEqual(cursor.execute.call_count, 1)
        connection.close.assert_called_once()


class ReadinessGateTest(unittest.TestCase):
    def test_pending_and_failed_documents_block_before_vector_access(self):
        with patch.object(uploads, "has_segments") as has:
            for state in ["pending", "failed"]:
                with self.subTest(state=state), self.assertRaisesRegex(ValueError, "not ready"):
                    uploads.require_ingested_documents([
                        {**DOCUMENT, "ingest_status": state, "ingest_error": "Indexing interrupted. Retry upload."}
                    ])
        has.assert_not_called()

    def test_complete_relational_document_without_vectors_is_blocked(self):
        with patch.object(uploads, "has_segments", return_value=False):
            with self.assertRaisesRegex(ValueError, "no vector index"):
                uploads.require_ingested_documents([DOCUMENT])

    def test_unavailable_vector_store_does_not_allow_generation(self):
        with patch.object(uploads, "has_segments", side_effect=ConnectionError("offline")):
            with self.assertRaisesRegex(ValueError, "vector store is unavailable"):
                uploads.require_ingested_documents([DOCUMENT])

    def test_complete_document_with_vectors_is_ready(self):
        with patch.object(uploads, "has_segments", return_value=True) as has:
            uploads.require_ingested_documents([DOCUMENT])
        has.assert_called_once_with(7)

    def test_chapter_loading_rejects_pending_document_before_reading_questions(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchone.return_value = {"id": 9, "title": "Trees"}
        cursor.fetchall.return_value = [{**DOCUMENT, "ingest_status": "pending"}]
        with patch.object(exams, "get_course", return_value={"id": 3}), patch.object(
            exams, "connect", return_value=connection
        ), patch.object(uploads, "has_segments") as has:
            with self.assertRaisesRegex(ValueError, "not ready"):
                exams.load_chapter(1, 3, 9)
        self.assertEqual(cursor.execute.call_count, 2)
        has.assert_not_called()
        connection.close.assert_called_once()

    def test_ready_chapter_retains_original_pdf_page(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchone.return_value = {"id": 9, "title": "Trees"}
        cursor.fetchall.side_effect = [
            [DOCUMENT],
            [{"id": 4, "name": "Binary tree"}],
            [{"document_id": 7, "page_number": 12, "filename": "lecture.pdf", "position": 1, "body": PAGES[0]["body"]}],
        ]
        with patch.object(exams, "get_course", return_value={"id": 3}), patch.object(
            exams, "connect", return_value=connection
        ), patch.object(uploads, "has_segments", return_value=True):
            chapter = exams.load_chapter(1, 3, 9)
        self.assertEqual(chapter["pages"][0]["page_number"], 12)
        self.assertEqual(chapter["concepts"], [{"id": 4, "name": "Binary tree"}])

    def test_existing_chapter_can_be_loaded_without_vector_access_for_recovery(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchone.return_value = {"id": 9, "title": "Trees"}
        cursor.fetchall.side_effect = [
            [{**DOCUMENT, "ingest_status": "failed"}],
            [{"id": 4, "name": "Binary tree"}],
            [{"document_id": 7, "page_number": 12, "body": PAGES[0]["body"]}],
        ]
        with patch.object(exams, "get_course", return_value={"id": 3}), patch.object(
            exams, "connect", return_value=connection
        ), patch.object(uploads, "has_segments") as has:
            chapter = exams.load_chapter(1, 3, 9, require_ready=False)
        has.assert_not_called()
        self.assertEqual(chapter["documents"][0]["ingest_status"], "failed")

    def test_plan_loading_does_not_silently_omit_failed_uploads(self):
        connection, cursor = connection_with_cursor()
        cursor.fetchall.return_value = [{**DOCUMENT, "ingest_status": "failed", "ingest_error": "Milvus offline"}]
        with patch.object(plans, "ensure_document_numbers"), patch.object(
            plans, "connect", return_value=connection
        ):
            with self.assertRaisesRegex(ValueError, "Milvus offline"):
                plans.load_usable_pages(3)
        self.assertEqual(cursor.execute.call_count, 1)
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
