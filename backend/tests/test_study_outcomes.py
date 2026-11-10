import copy
import json
import unittest

from db.study_status import _chapters, chapter_report, review_report


class OfficialPracticeOutcomeTest(unittest.TestCase):
    def test_one_finished_two_round_session_counts_two_independent_rounds(self):
        concepts = [{"chapter_id": 3, "chapter_title": "Trees", "concept_id": 1,
                     "concept_name": "Heap", "level": 2, "streak": 2}]
        report = {"outcome": "passed_round_2", "passed": True, "passing_threshold": .8,
                  "rounds": [{"round_number": 1, "score": 60, "passed": False},
                             {"round_number": 2, "score": 100, "passed": True}]}
        sessions = [{"chapter_id": 3, "status": "finished", "sessions": 1,
                     "correct_count": 8, "wrong_count": 2}]
        reports = [{"chapter_id": 3, "report_json": report}]
        record = {"chapters": _chapters(concepts, sessions, reports), "exams": {}}
        result = review_report(record, "")["matches"][0]
        self.assertEqual(result["finished_practice_sessions"], 1)
        self.assertEqual(result["finished_practice_rounds"], 2)
        self.assertEqual([item["score"] for item in result["round_scores"]], [60, 100])
        self.assertNotIn("score", result)

    def test_eighty_percent_pass_is_distinct_from_full_concept_mastery(self):
        concepts = [
            {"chapter_id": 3, "chapter_title": "Trees", "concept_id": index,
             "concept_name": f"Concept {index}", "level": 2 if index < 5 else 0,
             "streak": 2 if index < 5 else 0}
            for index in range(1, 6)
        ]
        official = {"outcome": "passed_round_1", "passed": True, "passing_threshold": .8,
                    "rounds": [{"round_number": 1, "correct_count": 8, "total": 10, "accuracy": .8, "passed": True}],
                    "remaining_weak_concepts": ["Concept 5"],
                    "remaining_sources": [{"document_id": 6, "page_number": 12}]}
        rows = [{"chapter_id": 3, "report_json": json.dumps(official)}]
        original = copy.deepcopy(rows)
        record = {"chapters": _chapters(concepts, [], rows), "exams": {}}
        result = chapter_report(record, "Trees")["matches"][0]
        self.assertTrue(result["chapter_passed"])
        self.assertFalse(result["mastered"])
        self.assertEqual(result["round_scores"][0]["correct_count"], 8)
        self.assertEqual(result["remaining_sources"][0]["page_number"], 12)
        self.assertEqual(review_report(record, "Trees")["matches"][0]["practice_outcome"], "passed_round_1")
        self.assertEqual(rows, original, "Reading Q&A study records must not mutate saved practice results")

    def test_legacy_history_is_not_presented_as_an_official_two_round_pass(self):
        rows = [{"chapter_id": 3, "report_json": {"outcome": "legacy", "passed": None}}]
        concepts = [{"chapter_id": 3, "chapter_title": "Trees", "concept_id": 1,
                     "concept_name": "Heap", "level": 2, "streak": 2}]
        record = {"chapters": _chapters(concepts, [], rows), "exams": {}}
        result = chapter_report(record, "")["matches"][0]
        self.assertTrue(result["mastered"])
        self.assertIsNone(result["chapter_passed"])


if __name__ == "__main__":
    unittest.main()
