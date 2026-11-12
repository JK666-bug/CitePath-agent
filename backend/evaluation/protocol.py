"""Frozen actual-grade workflow policy, separate from injected-count controller cases."""
from grading.score import exam_pass
from evaluation.core import require

POLICY = "actual_grade_v1"


def actual_grade_expectation(item, variant, rounds):
    """Derive expected behavior from independently validated observed integer counts.

    A full run that passed its first round must stop there. A failed first round
    requires exactly one follow-up. Missing observations remain unclassifiable.
    """
    threshold = item.get("scenario", {}).get("passing_threshold")
    require(type(threshold) in (int, float) and 0 < threshold <= 1, "Freeze a valid workflow passing threshold")
    if not rounds:
        return None
    require(isinstance(rounds, list) and all(isinstance(row, dict) for row in rounds), "Observed rounds must be an array")
    valid = True
    computed = []
    for number, row in enumerate(rounds, 1):
        correct, total = row.get("correct_count"), row.get("total")
        require(type(correct) is int and type(total) is int and 0 <= correct <= total and total > 0,
                "Observed round counts must be valid integers")
        passed = exam_pass(correct, total, threshold)
        valid = valid and type(row.get("round_number")) is int and row["round_number"] == number and type(row.get("passed")) is bool and row["passed"] == passed
        computed.append(passed)
    second_required = variant == "full" and not computed[0]
    required_rounds = 2 if second_required else 1
    valid = valid and len(rounds) == required_rounds
    branch = "first_round_pass" if computed[0] else "followup"
    required_branch = item.get("scenario", {}).get("required_branch")
    require(required_branch in {None, "first_round_pass", "followup"}, "Unknown required workflow branch")
    valid = valid and (required_branch is None or required_branch == branch)
    transitions = ["start", "round1_generated", "round1_submitted", "round1_scored"]
    actions = ["start_session", "record_saved_threshold_and_question_ids"]
    name = item.get("scenario", {}).get("name")
    if name in {"process_restart", "saved_draft_restore"}:
        actions += ["save_partial_answers", "restart_api_process", "resume_same_session", "assert_same_question_ids_and_drafts"]
    elif name == "model_timeout_then_retry":
        actions += ["inject_grader_timeout", "submit_answer", "assert_saved_draft_without_official_score", "restore_grader", "retry_same_submission"]
    actions += ["submit_first_round", "capture_first_round_grade_and_feedback"]
    duplicate = ["repeat_processed_submission_with_changed_response", "assert_original_grade_and_no_extra_grading_call"]
    if name == "duplicate_submit":
        actions += duplicate
    if name in {"independent_qa", "qa_between_rounds"}:
        actions += ["snapshot_practice_scores_round_and_status", "ask_independent_question", "assert_practice_snapshot_unchanged"]
    if second_required:
        transitions += ["round2_generated", "round2_submitted", "round2_scored"]
        actions += ["verify_second_round_targets_only_weak_concepts", "submit_second_round", "assert_round_scores_separate"]
    if name == "duplicate_after_final":
        actions += duplicate
    actions += ["capture_final_report", "assert_no_automatic_third_round", "reopen_and_verify_saved_result"]
    transitions += ["finished"]
    if variant == "baseline":
        outcome = "passed" if computed[0] else "failed"
    elif not second_required:
        outcome = "passed_round_1"
    else:
        outcome = "passed_round_2" if len(computed) > 1 and computed[1] else "failed_after_2"
    return {"transitions": transitions, "actions": actions, "final_state": outcome,
            "grade_consistent": valid, "required_rounds": required_rounds}
