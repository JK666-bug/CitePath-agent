import copy
import unittest

from agent.report_text import enrich_report


class ReportTextTest(unittest.TestCase):
    def test_two_round_prose_is_grounded_and_never_averages_or_mutates_results(self):
        report = {"outcome": "passed_round_2", "passed": True, "passing_threshold": .9,
                  "rounds": [{"round_number": 1, "correct_count": 7, "total": 10, "passed": False},
                             {"round_number": 2, "correct_count": 9, "total": 10, "passed": True}],
                  "remaining_weak_concepts": ["Hashing"], "wrong": [{"question_id": 22, "round_number": 2,
                    "concept_name": "Hashing", "explanation_status": "failed", "explanation": "",
                    "sources": [{"document_id": 4, "page_number": 3}]}]}
        original = copy.deepcopy(report)
        result = enrich_report(report)
        self.assertEqual(report, original)
        self.assertEqual(result["rounds"], original["rounds"])
        self.assertIn("round 2", result["summary"])
        self.assertIn("7 of 10", result["round_summaries"][0])
        self.assertIn("90%", result["round_summaries"][1])
        self.assertNotIn("80%", str(result))
        self.assertEqual(result["review_guidance"][0]["sources"], original["wrong"][0]["sources"])
        self.assertEqual(result["feedback_pending_count"], 1)

    def test_rounding_cannot_make_failed_session_prose_claim_pass(self):
        result = enrich_report({"outcome": "failed_after_2", "passing_threshold": .8,
            "rounds": [{"round_number": 2, "correct_count": 159, "total": 200, "score": 80, "passed": False}]})
        self.assertIn("79.5%", result["round_summaries"][0])
        self.assertIn("did not meet", result["round_summaries"][0])
        self.assertIn("without reaching", result["summary"])

    def test_legacy_is_not_presented_as_an_official_pass(self):
        result = enrich_report({"outcome": "legacy", "wrong": []})
        self.assertIn("no official", result["summary"])
        self.assertEqual(result["round_summaries"], [])

    def test_ready_retry_removes_pending_notice_without_touching_rounds(self):
        report = {"outcome": "passed_round_1", "wrong": [{"concept_name": "A", "explanation_status": "ready", "explanation": "A fact."}],
                  "remaining_weak_concepts": [], "rounds": [{"round_number": 1, "correct_count": 4, "total": 5, "passed": True}]}
        result = enrich_report(report)
        self.assertEqual(result["feedback_pending_count"], 0)
        self.assertNotIn("unavailable", result["summary"])
        self.assertEqual(result["review_guidance"], [])


if __name__ == "__main__":
    unittest.main()
