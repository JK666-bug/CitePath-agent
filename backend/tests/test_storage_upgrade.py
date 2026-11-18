"""Compatibility at the old-data/new-feature boundary, with no live services."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from db import courses, document_files, pdf_store, plans, practice, qa, uploads
from tools import rebuild_vector_index
from vector import segments


class PdfUpgradeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {"PDF_STORAGE_DIR": str(self.root / "old")})
        env.start()
        self.addCleanup(env.stop)
        new = patch.object(pdf_store, "PDF_ROOT", self.root / "new")
        new.start()
        self.addCleanup(new.stop)

    def test_both_layouts_read_without_moving_either_original(self):
        legacy = document_files.save_original_pdf(7, b"old original")
        pdf_store.save_pdf(3, 8, b"new original")
        self.assertEqual(pdf_store.available_pdf_path(3, 7), legacy)
        self.assertEqual(pdf_store.read_pdf_bytes(3, 7), b"old original")
        self.assertEqual(pdf_store.read_pdf_bytes(3, 8), b"new original")
        self.assertTrue(legacy.exists())
        self.assertTrue(pdf_store.pdf_path(3, 8).exists())

    def test_failed_replace_retains_existing_new_layout_original(self):
        pdf_store.save_pdf(3, 8, b"saved")
        with patch.object(pdf_store.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                pdf_store.save_pdf(3, 8, b"replacement")
        self.assertEqual(pdf_store.read_pdf_bytes(3, 8), b"saved")
        self.assertEqual(len(list((self.root / "new" / "3").iterdir())), 1)

    def test_archive_retains_original_bytes_in_both_layouts(self):
        old = document_files.save_original_pdf(7, b"old original")
        pdf_store.save_pdf(3, 7, b"new original")
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [{"course_id": 3}, {"id": 3}]
        cursor.fetchall.return_value = []
        with patch.object(courses, "connect", return_value=connection):
            courses._archive_document(7)
        self.assertEqual(old.read_bytes(), b"old original")
        self.assertEqual(pdf_store.pdf_path(3, 7).read_bytes(), b"new original")


class LegacyVectorTest(unittest.TestCase):
    def client(self, fields=("sparse", "vector")):
        client = MagicMock()
        client.has_collection.return_value = True
        client.describe_collection.return_value = {"fields": [{"name": name} for name in fields]}
        return client

    def test_old_hybrid_collection_is_usable_and_never_dropped(self):
        client = self.client()
        self.assertTrue(segments._usable_collection(client))
        segments._ensure_collection(client, 384)
        self.assertNotIn("bridge_to", segments._output_fields(client, ["text", "bridge_to"]))
        client.drop_collection.assert_not_called()
        client.create_collection.assert_not_called()

    def test_incompatible_collection_is_retained_on_read_write_and_delete(self):
        client = self.client(("vector",))
        for operation in (lambda: segments._usable_collection(client),
                          lambda: segments._ensure_collection(client, 384),
                          lambda: segments._delete_document(client, 7)):
            with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                operation()
        client.drop_collection.assert_not_called()
        client.delete.assert_not_called()

    def test_old_collection_write_omits_new_field_without_destroying_collection(self):
        client = self.client()
        client.query.return_value = []
        piece = {"document_id": 7, "page_number": 1, "chunk_index": 0, "chapter": "", "text": "text", "bridge_to": 2}
        with patch.object(segments, "_client", return_value=client), patch.object(segments, "_pieces", return_value=[{**piece, "bridge_to": 0}, piece]), patch.object(segments, "_embed", return_value=[[0.1] * 384, [0.2] * 384]):
            self.assertEqual(segments.sync_pages(7, []), 1)
        self.assertNotIn("bridge_to", client.insert.call_args.kwargs["data"][0])
        client.drop_collection.assert_not_called()

    def test_new_collection_write_and_read_preserve_bridge_metadata(self):
        client = self.client(("sparse", "vector", "bridge_to"))
        self.assertIn("bridge_to", segments._output_fields(client, ["text", "bridge_to"]))
        client.query.return_value = [{"document_id": 7, "page_number": 1, "chunk_index": 0, "bridge_to": 2}]
        with patch.object(segments, "_client", return_value=client):
            self.assertEqual(segments.segments_for(7)[0]["bridge_to"], 2)


class SelectedMaterialTest(unittest.TestCase):
    def test_same_pdf_cannot_be_reused_as_lecture_when_it_is_a_sample(self):
        with patch.object(uploads, "ensure_document_numbers"), patch.object(uploads, "_hash_row", return_value={"id": 7, "kind": "exam_case"}), patch.object(uploads, "_restore_upload") as restore, patch.object(uploads, "_store_original_pdf") as store:
            with self.assertRaisesRegex(ValueError, "another role"):
                uploads.existing_upload(3, "same-hash")
        restore.assert_not_called()
        store.assert_not_called()

    def test_selection_is_owned_active_lecture_and_readiness_checked(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [[{"id": 7}], [{"document_id": 7, "page_number": 4}]]
        with patch.object(plans, "ensure_document_numbers"), patch.object(plans, "connect", return_value=connection), patch.object(plans, "require_ingested_documents") as ready:
            pages = plans.load_usable_pages(3, document_ids=[7, 7])
        self.assertEqual(pages[0]["page_number"], 4)
        ready.assert_called_once_with([{"id": 7}])
        for call in cursor.execute.call_args_list:
            self.assertIn("d.is_active = 1", call.args[0])
            self.assertIn("d.kind = 'lecture'", call.args[0])
            self.assertEqual(call.args[1], [3, 7])

    def test_foreign_archived_or_sample_selection_rejects_before_vector_access(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        with patch.object(plans, "ensure_document_numbers"), patch.object(plans, "connect", return_value=connection), patch.object(plans, "require_ingested_documents") as ready:
            with self.assertRaisesRegex(ValueError, "unavailable"):
                plans.load_usable_pages(3, document_ids=[7])
        ready.assert_not_called()

    def test_qa_leading_and_overview_pages_exclude_archived_samples(self):
        for loader in (qa.load_leading_pages, qa.load_overview_pages):
            connection = MagicMock()
            cursor = connection.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = []
            with patch.object(qa, "connect", return_value=connection):
                self.assertEqual(loader([7]), [])
            self.assertIn("d.is_active = 1", cursor.execute.call_args.args[0])
            self.assertIn("d.kind = 'lecture'", cursor.execute.call_args.args[0])

    def test_threshold_and_prefs_are_saved_as_distinct_fields(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.lastrowid = 9
        with patch.object(practice, "ensure_practice_storage"), patch.object(practice, "connect", return_value=connection):
            self.assertEqual(practice.create_session(1, 3, {"id": 4, "title": "Trees"}, 0.7, prefs={"difficulty": "hard"}), 9)
        values = cursor.execute.call_args.args[1]
        self.assertEqual(values[-2], "0.7")
        self.assertIn('"difficulty": "hard"', values[-1])


class ReplacementIndexTest(unittest.TestCase):
    def test_dry_run_does_not_create_replace_or_drop_collections(self):
        connection, client = MagicMock(), MagicMock()
        client.has_collection.return_value = False
        snapshot = {"documents": [], "pages": [], "fingerprint": "same"}
        with patch.object(rebuild_vector_index, "material_snapshot", return_value=snapshot):
            report = rebuild_vector_index.rebuild("lecture_segments_v2", connection=connection, client=client)
        self.assertFalse(report["applied"])
        self.assertFalse(report["activated"])
        client.create_collection.assert_not_called()
        client.drop_collection.assert_not_called()

    def test_existing_target_is_not_overwritten(self):
        client = MagicMock()
        client.has_collection.return_value = True
        with self.assertRaisesRegex(ValueError, "already exists"):
            rebuild_vector_index.rebuild("lecture_segments_v2", connection=MagicMock(), client=client, apply=True)
        client.drop_collection.assert_not_called()

    def test_source_change_keeps_original_collection_selected(self):
        source = segments.COLLECTION
        client = MagicMock()
        client.has_collection.return_value = False
        snapshot = {"documents": [], "pages": [], "fingerprint": "before"}
        with patch.object(rebuild_vector_index, "material_snapshot", side_effect=[snapshot, {**snapshot, "fingerprint": "after"}]), patch.object(segments, "_ensure_collection"):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                rebuild_vector_index.rebuild("lecture_segments_v2", connection=MagicMock(), client=client, apply=True)
        self.assertEqual(segments.COLLECTION, source)
        client.drop_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
