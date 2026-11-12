import copy
import unittest
from evaluation.core import _workflow_runs
from evaluation.protocol import actual_grade_expectation


def item(threshold=.8, name="decision"):
    return {"id": "WF", "scenario": {"name": name, "passing_threshold": threshold},
            "expected": {variant: {"policy": "actual_grade_v1"} for variant in ("baseline", "full")}}


def rounds(first=4, total=5, second=None, threshold=.8):
    from grading.score import exam_pass
    result = [{"round_number": 1, "correct_count": first, "total": total, "passed": exam_pass(first, total, threshold)}]
    if second is not None:
        result.append({"round_number": 2, "correct_count": second, "total": 5, "passed": exam_pass(second, 5, threshold)})
    return result


class ActualGradeProtocolTest(unittest.TestCase):
    def test_equal_threshold_stops_after_one_and_separates_baseline_outcome(self):
        observed = rounds()
        full = actual_grade_expectation(item(), "full", observed)
        baseline = actual_grade_expectation(item(), "baseline", observed)
        self.assertEqual(full["final_state"], "passed_round_1")
        self.assertEqual(baseline["final_state"], "passed")
        self.assertEqual(full["required_rounds"], 1)

    def test_unrounded_boundary_and_second_round_have_independent_decisions(self):
        rule = actual_grade_expectation(item(), "full", rounds(159, 200, 4))
        self.assertEqual(rule["final_state"], "passed_round_2")
        self.assertTrue(rule["grade_consistent"])
        self.assertEqual(rule["required_rounds"], 2)

    def test_premature_completion_or_followup_after_pass_are_failed_observations(self):
        for observed in (rounds(3, 5), rounds(4, 5, 5)):
            rule = actual_grade_expectation(item(), "full", observed)
            self.assertFalse(rule["grade_consistent"])

    def test_reported_pass_cannot_override_integer_counts(self):
        observed = rounds(159, 200, 4)
        observed[0]["passed"] = True
        self.assertFalse(actual_grade_expectation(item(), "full", observed)["grade_consistent"])
        observed[0]["correct_count"] = True
        with self.assertRaises(ValueError):
            actual_grade_expectation(item(), "full", observed)

    def test_unknown_grades_remain_pending_and_valid_observations_can_be_scored(self):
        frozen = item()
        empty = _workflow_runs(frozen, "full", {"runs": []})
        self.assertTrue(all(row["passed"] is None for row in empty))
        actual = rounds(3, 5, 4)
        rule = actual_grade_expectation(frozen, "full", actual)
        run = {"repeat": 1, "observed_rounds": actual, "round_count": 2, "passing_threshold": .8,
               "observation_status": "completed", "third_round": False, "duplicate_scoring": False, "qa_score_changed": False,
               **{key: rule[key] for key in ("actions", "transitions", "final_state")}}
        self.assertTrue(_workflow_runs(frozen, "full", {"runs": [run]})[0]["passed"])
        changed = copy.deepcopy(run)
        changed["third_round"] = True
        self.assertFalse(_workflow_runs(frozen, "full", {"runs": [changed]})[0]["passed"])

    def test_duplicate_after_final_probe_is_ordered_after_second_round(self):
        rule = actual_grade_expectation(item(name="duplicate_after_final"), "full", rounds(3, 5, 4))
        self.assertGreater(rule["actions"].index("repeat_processed_submission_with_changed_response"),
                           rule["actions"].index("assert_round_scores_separate"))

    def test_required_branch_is_not_claimed_when_actual_grades_take_another_branch(self):
        frozen = item()
        frozen["scenario"]["required_branch"] = "followup"
        rule = actual_grade_expectation(frozen, "full", rounds())
        self.assertEqual(rule["final_state"], "passed_round_1")
        self.assertFalse(rule["grade_consistent"])


if __name__ == "__main__":
    unittest.main()
