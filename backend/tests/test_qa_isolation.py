import unittest
from unittest.mock import patch

from agent.qa import answer_question


class QaIsolationTest(unittest.TestCase):
    def test_lecture_answer_writes_only_qa_history(self):
        course = {"id": 2, "name": "Trees", "documents": [{
            "id": 6, "ingest_status": "complete", "usable_page_count": 3}]}
        page = {"document_id": 6, "page_number": 3, "filename": "trees.pdf", "body": "A tree has a root."}
        parsed = {"supported": True, "answer": "A tree has a root.", "cited_pages": [{"document_id": 6, "page_number": 3}]}
        with patch("agent.qa.get_course", return_value=course), \
                patch("agent.qa._choose_and_answer", return_value=([page], parsed, False, [], False)), \
                patch("agent.qa.insert_record", return_value={"qa_id": 8, "tab_id": "tab-8", "tab_title": "Trees"}) as history, \
                patch("db.practice.save_answer") as practice_score, \
                patch("db.practice.save_round_results") as round_state, \
                patch("db.exams.finish_exam") as exam_score:
            result = answer_question(1, 2, "What is a tree?")
            self.assertEqual(result["cited_pages"][0]["document_id"], 6)
            self.assertEqual(result["cited_pages"][0]["page_number"], 3)
            history.assert_called_once()
            practice_score.assert_not_called()
            round_state.assert_not_called()
            exam_score.assert_not_called()


if __name__ == "__main__":
    unittest.main()
