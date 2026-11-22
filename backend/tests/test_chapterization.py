import unittest

from db.chapterization import (
    ChapterizationConflict,
    choose_documents,
)


def document(document_id, state, eligible=True):
    return {
        "id": document_id,
        "filename": f"{document_id}.pdf",
        "state": state,
        "eligible": eligible,
        "reason": "" if eligible else "learning_started",
    }


class ChapterizationRulesTest(unittest.TestCase):
    def test_only_new_pdfs_are_selected_automatically(self):
        documents = [
            document(1, "planned"),
            document(2, "unplanned"),
            document(3, "locked", False),
        ]

        self.assertEqual(
            choose_documents(documents, [], False),
            [2],
        )

    def test_existing_pdf_is_not_selected_with_new_pdf(self):
        documents = [
            document(1, "planned"),
            document(2, "unplanned"),
        ]

        with self.assertRaises(ChapterizationConflict):
            choose_documents(documents, [1, 2], False)

    def test_planned_pdf_requires_confirmation(self):
        documents = [document(1, "planned")]

        with self.assertRaises(ChapterizationConflict):
            choose_documents(documents, [1], False)

        self.assertEqual(
            choose_documents(documents, [1], True),
            [1],
        )

    def test_locked_pdf_cannot_be_rebuilt(self):
        documents = [
            document(1, "planned"),
            document(2, "locked", False),
        ]

        with self.assertRaises(ChapterizationConflict):
            choose_documents(documents, [2], True)

    def test_no_eligible_pdf_is_rejected(self):
        documents = [
            document(1, "locked", False),
        ]

        with self.assertRaises(ChapterizationConflict):
            choose_documents(documents, [], False)

    def test_confirmation_does_not_override_new_pdf_priority(self):
        documents = [
            document(1, "planned"),
            document(2, "unplanned"),
        ]

        with self.assertRaises(ChapterizationConflict):
            choose_documents(documents, [1], True)

    def test_duplicate_document_ids_are_removed(self):
        documents = [document(1, "planned")]

        self.assertEqual(
            choose_documents(documents, [1, 1], True),
            [1],
        )


if __name__ == "__main__":
    unittest.main()