import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent import qa


def pdf_page(number, body, document_id=7):
    return {"document_id": document_id, "page_number": number, "filename": "lecture.pdf", "body": body}


def cited_reply(number, document_id=7):
    return AIMessage(content=json.dumps({
        "answer": "Evidence from the lecture.",
        "cited_pages": [{"document_id": document_id, "page_number": number}],
    }))


class ReadingQATest(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(qa, "get_course", return_value={
            "id": 20, "name": "Reading fixture",
            "documents": [{"id": 7, "ingest_status": "complete", "usable_page_count": 50}],
        }))
        stack.enter_context(patch.object(qa, "recent_turns", return_value=[]))
        stack.enter_context(patch.object(qa, "insert_record", return_value={
            "qa_id": 1, "tab_id": "read-1", "tab_title": "Reading",
        }))

    def test_search_reaches_late_page_and_ignores_other_documents(self):
        body = "Zeta reconciliation appears here."
        hit = {"document_id": 7, "page_number": 50, "text": body, "score": 1.0}
        with patch.object(qa, "search", return_value=[{**hit, "document_id": 99}, hit]) as search, \
             patch.object(qa, "rerank", side_effect=lambda _, hits: hits), \
             patch.object(qa, "load_page_bodies", return_value={(7, 50): pdf_page(50, body)}) as load, \
             patch.object(qa, "invoke_messages", return_value=cited_reply(50)) as model:
            result = qa.answer_attached_chat(10, 20, "What is zeta reconciliation?", [7], "read-1")
        self.assertFalse(result["refused"])
        self.assertEqual(result["cited_pages"], [{"document_id": 7, "page_number": 50, "filename": "lecture.pdf"}])
        search.assert_called_once_with([7], "What is zeta reconciliation?", limit=qa.CANDIDATES)
        load.assert_called_once_with([(7, 50)])
        self.assertIn(body, model.call_args.args[0][-1].content)

    def test_vector_outage_falls_back_to_the_entire_pdf(self):
        rows = [pdf_page(i, "Background and general concepts") for i in range(1, 50)]
        rows.append(pdf_page(50, "比较缺失值填补方法"))
        with patch.object(qa, "_retrieve", side_effect=RuntimeError("vector service down")), \
             patch.object(qa, "load_document_pages", return_value=rows) as load, \
             patch.object(qa, "invoke_messages", return_value=cited_reply(50)):
            result = qa.answer_attached_chat(10, 20, "在整份 PDF 中，怎么比较缺失值填补？", [7])
        load.assert_called_once_with([7])
        self.assertEqual([source["page_number"] for source in result["cited_pages"]], [50])

    def test_page_references_use_the_requested_page(self):
        for question, page_number in (("解释第 50 页", None), ("Explain page 50", None), ("Explain this", 50)):
            with self.subTest(question=question), \
                 patch.object(qa, "_retrieve") as search, \
                 patch.object(qa, "load_page_bodies", return_value={(7, 50): pdf_page(50, "Evidence")}) as load, \
                 patch.object(qa, "invoke_messages", return_value=cited_reply(50)):
                result = qa.answer_attached_chat(10, 20, question, [7], page_number=page_number)
                self.assertFalse(result["refused"])
                load.assert_called_once_with([(7, 50)])
                search.assert_not_called()

    def test_unreadable_page_reports_the_problem_before_calling_model(self):
        with patch.object(qa, "load_page_bodies", return_value={}), patch.object(qa, "invoke_messages") as model:
            with self.assertRaisesRegex(ValueError, "No readable text.*50"):
                qa.answer_attached_chat(10, 20, "Explain this", [7], page_number=50)
        model.assert_not_called()

    def test_summary_batches_cover_the_front_middle_and_end(self):
        rows = [pdf_page(i, f"MARKER_{i} " + "x" * qa.PAGE_CHARS) for i in range(1, 7)]
        batches = []

        def model(messages):
            if messages[0].content == qa.READING_SUMMARY_SYSTEM:
                batches.append(messages[-1].content)
                return AIMessage(content="Summary with the original page references.")
            return cited_reply(6)

        with patch.object(qa, "load_document_pages", return_value=rows) as load, \
             patch.object(qa, "_retrieve") as search, patch.object(qa, "invoke_messages", side_effect=model):
            result = qa.answer_attached_chat(10, 20, "What does this PDF cover?", [7])
        load.assert_called_once_with([7])
        search.assert_not_called()
        self.assertEqual(len(batches), 3)
        for i in range(1, 7):
            self.assertTrue(any(f"MARKER_{i} " in batch for batch in batches))
        self.assertEqual([source["page_number"] for source in result["cited_pages"]], [6])

    def test_rejects_sources_outside_the_pdf_or_supplied_pages(self):
        for document_id, page in ((99, 50), (7, 1)):
            with self.subTest(document_id=document_id, page=page), \
                 patch.object(qa, "_reading_search", return_value=[pdf_page(50, "Evidence")]), \
                 patch.object(qa, "invoke_messages", return_value=cited_reply(page, document_id)):
                result = qa.answer_attached_chat(10, 20, "What is discussed?", [7])
                self.assertTrue(result["refused"])
                self.assertEqual(result["cited_pages"], [])

    def test_chinese_pdf_filename_can_be_opened_at_a_citation(self):
        from main import document_file

        data = b"%PDF-1.4"
        with patch("main.owns_document", return_value=True), \
             patch("main.get_course", return_value={"documents": [{"id": 7, "filename": "第4章.pdf"}]}), \
             patch("db.pdf_store.read_pdf_bytes", return_value=data):
            response = document_file(20, 7, {"id": 10})
        self.assertEqual(response.body, data)
        self.assertIn("filename*=UTF-8''%E7%AC%AC4%E7%AB%A0.pdf", response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
