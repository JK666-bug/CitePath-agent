"""Paired, resumable workflow observations using isolated application sessions.

First-round questions, responses, grades and feedback are collected once and
replayed into separate baseline/full sessions. The baseline's one-round stopping
rule is internal to this evaluator; the application's two-round rule is unchanged.
No action or transition is copied from a scenario's expected results.
"""
import copy
import time
from datetime import datetime, timezone

from evaluation.core import VARIANTS, _freeze_problems, digest, require, validate_dataset
from evaluation.session_store import CheckpointStore

SCHEMA = "citepath-workflow-collection-v1"
UNSUPPORTED = {"process_restart", "saved_draft_restore", "model_timeout_then_retry"}
QA_SCENARIOS = {"independent_qa", "qa_between_rounds"}
DUPLICATE_SCENARIOS = {"duplicate_submit", "duplicate_after_final"}


def now():
    return datetime.now(timezone.utc).isoformat()


def response_for(question, answers, round_number):
    selected = answers.get(f"round{round_number}", answers)
    require(isinstance(selected, dict), "A round response policy must be an object")
    if selected.get("policy") in {"reference", "wrong_reference"}:
        if question["kind"] == "mcq":
            key = str(question.get("answer") or "").strip().upper()
            require(key in {"A", "B", "C", "D"}, "A reference response requires the saved candidate answer")
            return key if selected["policy"] == "reference" else ("B" if key == "A" else "A")
        if selected["policy"] == "wrong_reference":
            return "I cannot answer this concept."
        rubric = question.get("rubric") or question.get("rubric_json")
        if isinstance(rubric, str):
            import json
            rubric = json.loads(rubric)
        require(isinstance(rubric, list) and rubric and all(isinstance(point, str) for point in rubric), "A reference response requires saved rubric points")
        response = "; ".join(rubric)
        require(len(response) <= 5000, "Reference response exceeds the submission limit")
        return response
    require(selected.get("policy") is None, "Unknown recorded response policy")
    response = (selected.get("by_prompt_sha256") or {}).get(digest(question["prompt"]))
    if response is None:
        response = selected.get(question["kind"])
    require(isinstance(response, str) and response.strip() and len(response) <= 5000,
            "Provide a nonempty recorded response for each question kind/prompt")
    if question["kind"] == "mcq":
        require(response.strip().upper() in {"A", "B", "C", "D"}, "MCQ response must be A, B, C or D")
    return response.strip()


def binding_for(bindings, item, repeat):
    pair = (bindings.get("cases", {}).get(item["id"], {}).get(str(repeat))
            or bindings.get("by_lecture", {}).get(str(item["lecture"])))
    require(isinstance(pair, dict), f"Missing dedicated workflow binding for {item['id']}/{repeat}")
    identities = []
    for role in ("shared", *VARIANTS):
        fixture = pair.get(role)
        require(isinstance(fixture, dict) and all(type(fixture.get(field)) is int and fixture[field] > 0
                                                for field in ("user_id", "course_id", "chapter_id")),
                f"Invalid dedicated {role} fixture")
        identities.append(tuple(fixture[field] for field in ("user_id", "course_id", "chapter_id")))
    require(len(set(identities)) == 3, "Shared, baseline and full sessions need isolated fixtures")
    return pair


def canonical_bank(bank):
    """Stable comparison excludes only database IDs, not answer/feedback content."""
    return [{key: row.get(key) for key in (
        "concept_name", "kind", "prompt", "options", "answer", "rubric", "source_content",
        "response", "correct", "points_hit", "points_total", "rubric_hits", "explanation",
        "explanation_status", "explanation_error", "explanation_attempts",
    )} for row in bank if int(row.get("round_number", 1)) == 1]


def grade_snapshot(state):
    report = state.get("report") or {}
    return digest({"status": state["status"], "round_results": state["round_results"],
                   "round_number": state["round_number"], "passing_threshold": state["passing_threshold"],
                   "report": {key: report.get(key) for key in ("passed", "outcome", "rounds", "passing_threshold", "correct_count", "question_count", "started_at", "finished_at")},
                   "concepts": state.get("concepts"),
                   "grades": [{key: row.get(key) for key in ("question_id", "response", "correct", "points_hit", "points_total", "rubric_hits",
                                                                         "prompt", "answer", "rubric", "sources", "source_content", "kind", "round_number")}
                              for row in state["bank"]]})


def collect_workflows(data, *, bindings, answers, checkpoint_dir, adapter=None, repeats=3,
                      allow_create_sessions=False):
    chosen = adapter or MySQLPracticeAdapter()
    try:
        return _collect_workflows(data, bindings=bindings, answers=answers, checkpoint_dir=checkpoint_dir,
                                  adapter=chosen, repeats=repeats, allow_create_sessions=allow_create_sessions)
    finally:
        if type(chosen) is MySQLPracticeAdapter:
            chosen.close()


def _collect_workflows(data, *, bindings, answers, checkpoint_dir, adapter=None, repeats=3,
                      allow_create_sessions=False):
    """Collect up to 20×2×3 actual runs; blocked/unobserved work stays explicit.

    A custom adapter must declare synthetic=True. Such observations are returned
    under controller_records, never under importable formal records.
    """
    validate_dataset(data)
    require(not _freeze_problems(data), "Freeze the cohort before workflow collection")
    require(type(repeats) is int and 1 <= repeats <= 3, "repeats must be 1, 2 or 3")
    require(isinstance(bindings, dict) and isinstance(answers, dict), "Bindings and recorded answers must be objects")
    require(bindings.get("dataset_sha256") == digest(data), "Workflow bindings belong to another dataset")
    require(bindings.get("configuration_sha256") == data["freeze"]["manifest_sha256"], "Workflow bindings use another configuration")
    if data["split"] == "final" and not data["synthetic"] and any(
            expected.get("policy") == "actual_grade_v1" for item in data["items"]
            for expected in (item.get("expected") or {}).values()):
        require((data.get("evaluation_protocol") or {}).get("chapter_mapping_sha256") == digest(bindings.get("cases")),
                "Runtime fixtures differ from the human-reviewed chapter mapping")
        require((data.get("evaluation_protocol") or {}).get("response_policy_sha256") == digest(answers),
                "Response policy differs from the human-reviewed frozen inputs")
    adapter = adapter or MySQLPracticeAdapter()
    synthetic = type(adapter) is not MySQLPracticeAdapter
    require(not synthetic or adapter.synthetic is True, "Injected adapters must declare synthetic=True")
    report = {"schema": SCHEMA, "dataset_sha256": digest(data), "records": [], "controller_records": [],
              "synthetic": synthetic, "formal_model_quality": False, "started_at": now(),
              "status": "not_run", "run_statuses": [], "limits": [
                  "Controller and injected runs are not formal model-quality evidence.",
                  "Process restart and timeout require real operation adapters; absent adapters remain not_run.",
                  "Cached sessions are retained; no account, course, question or grade is deleted."]}
    if not allow_create_sessions:
        report["reason"] = "explicit_create_evaluation_sessions_flag_required"
        return report
    # Runtime/model/source checks happen before any application database writes.
    configuration = adapter.verify_configuration(data, bindings)
    items = [item for item in data["items"] if item["kind"] == "workflow"]
    require(len(items) <= 20, "At most twenty frozen workflow scenarios are supported")
    pairs = {(item["id"], repeat): binding_for(bindings, item, repeat)
             for item in items for repeat in range(1, repeats + 1)}
    identities = [tuple(pair[role][field] for field in ("user_id", "course_id", "chapter_id"))
                  for pair in pairs.values() for role in ("shared", *VARIANTS)]
    require(len(identities) == len(set(identities)), "Every scenario/repeat needs isolated fixtures; history cannot carry between runs")
    for (item_id, repeat), pair in pairs.items():
        adapter.validate_pair(pair)
        if type(adapter) is MySQLPracticeAdapter:
            adapter.validate_case(pair, next(item for item in items if item["id"] == item_id))
    identity = {"dataset_sha256": digest(data), "configuration_sha256": data["freeze"]["manifest_sha256"],
                "bindings_sha256": digest(bindings), "answers_sha256": digest(answers), "synthetic": synthetic}
    store = CheckpointStore(checkpoint_dir, identity)
    with store.exclusive():
        for item in items:
            runs = {variant: [] for variant in VARIANTS}
            for repeat in range(1, repeats + 1):
                key = f"{item['id']}-{repeat}"
                checkpoint = store.load(key)
                if checkpoint.get("complete"):
                    result = checkpoint["runs"]
                elif item.get("scenario", {}).get("name") in UNSUPPORTED and not adapter.supports(item["scenario"]["name"]):
                    result = {variant: pending_run(repeat, "real_fault_or_process_adapter_unavailable") for variant in VARIANTS}
                    checkpoint.update({"complete": True, "runs": result})
                    store.save(key, checkpoint)
                else:
                    try:
                        from agent.telemetry import usage_context
                        with usage_context(operation="evaluation.workflow", evaluation_id=data["evaluation_id"], item_id=item["id"], repeat=repeat):
                            if type(adapter) is MySQLPracticeAdapter:
                                adapter.verify_current()
                            result = execute_pair(item, repeat, pairs[(item["id"], repeat)], answers,
                                                  adapter, checkpoint, lambda: store.save(key, checkpoint))
                        checkpoint.update({"complete": True, "runs": result})
                        store.save(key, checkpoint)
                    except (Exception, KeyboardInterrupt) as error:
                        # Completed sub-runs and committed answers remain resumable.
                        result = checkpoint.get("runs", {}).copy()
                        for variant in VARIANTS:
                            if variant not in result:
                                result[variant] = partial_run(repeat, checkpoint, variant, adapter,
                                    pairs[(item["id"], repeat)][variant], inspect_state=not isinstance(error, KeyboardInterrupt))
                        checkpoint["last_failure"] = type(error).__name__
                        store.save(key, checkpoint)
                        if isinstance(error, KeyboardInterrupt):
                            raise
                for variant in VARIANTS:
                    runs[variant].append(result[variant])
                    report["run_statuses"].append({"item_id": item["id"], "variant": variant, "repeat": repeat,
                                                   "status": result[variant]["observation_status"]})
            for variant in VARIANTS:
                prediction = {"collected_at": now(), "configuration_sha256": data["freeze"]["manifest_sha256"],
                              "model": configuration["model"], "provider": configuration["provider"],
                              "base_url_sha256": configuration["base_url_sha256"], "collector": "paired_production_workflow",
                              "chapter_mapping_sha256": digest(bindings.get("cases")),
                              "response_policy_sha256": digest(answers),
                              "synthetic": synthetic, "runs": runs[variant]}
                report["controller_records" if synthetic else "records"].append(
                    {"item_id": item["id"], "variant": variant, "prediction": prediction})
    report["status"] = "completed" if report["run_statuses"] and all(row["status"] in {"completed", "mismatch"} for row in report["run_statuses"]) else "pending"
    report["observed_mismatches"] = sum(row["status"] == "mismatch" for row in report["run_statuses"])
    report["finished_at"] = now()
    return report


def pending_run(repeat, reason, status="not_run"):
    return {"repeat": repeat, "observation_status": status, "reason": reason, "actions": [], "transitions": [],
            "final_state": None, "round_count": None, "third_round": None, "duplicate_scoring": None,
            "qa_score_changed": None, "scenario_match": None}


def partial_run(repeat, checkpoint, variant, adapter, fixture, inspect_state=True):
    run = pending_run(repeat, "collection_interrupted", "failed")
    probes = checkpoint.get("probes", {}).get(variant, {})
    for name, flag in (("duplicate", "duplicate_scoring"), ("qa", "qa_score_changed")):
        if probes.get(name, {}).get("done"):
            run[flag] = bool(probes[name]["changed"])
    session_id = checkpoint.get("sessions", {}).get(variant)
    if inspect_state and session_id is not None:
        try:
            state = adapter.state(fixture, session_id)
            count = max((row["round_number"] for row in state["bank"]), default=0)
            run["round_count"] = count
            if count > (1 if variant == "baseline" else 2):
                run["third_round"] = True
            for name, flag in (("duplicate", "duplicate_scoring"), ("qa", "qa_score_changed")):
                before = probes.get(name, {}).get("before_sha256")
                if before and not probes[name].get("done") and grade_snapshot(state) != before:
                    run[flag] = True
        except Exception:
            pass
    known = checkpoint.setdefault("known_prohibited", {}).setdefault(variant, {})
    for flag in ("third_round", "duplicate_scoring", "qa_score_changed"):
        if run[flag] is True:
            known[flag] = True
        if known.get(flag):
            run[flag] = True
    return run


def execute_pair(item, repeat, pair, answers, adapter, checkpoint, save):
    threshold = item.get("scenario", {}).get("passing_threshold", .8)
    name = item.get("scenario", {}).get("name", "")
    selected = (answers.get("by_scenario") or {}).get(item["id"], answers)
    if "shared_session" not in checkpoint:
        require(not checkpoint.get("creating_shared_session"), "Shared-session creation is uncertain; reconcile it before resuming")
        checkpoint["creating_shared_session"] = True
        save()
        checkpoint["shared_session"] = adapter.create(pair["shared"], threshold)
        checkpoint["creating_shared_session"] = False
        save()
    if "shared_bank" not in checkpoint:
        if name == "model_timeout_then_retry":
            require(not checkpoint.get("shared_fault_pending"), "Shared timeout probe is uncertain; reconcile it before resuming")
            checkpoint["shared_fault_pending"] = True
            save()
        checkpoint["shared_events"] = adapter.prepare_shared(pair["shared"], checkpoint["shared_session"],
            {**selected, "_inject_shared_timeout": name == "model_timeout_then_retry"}) or {}
        checkpoint["shared_fault_pending"] = False
        # Close the common one-round cache so merely opening its retained
        # history cannot trigger a production follow-up or another model call.
        adapter.advance(pair["shared"], checkpoint["shared_session"], "baseline")
        checkpoint["shared_bank"] = adapter.state(pair["shared"], checkpoint["shared_session"])["bank"]
        checkpoint["first_round_sha256"] = digest(canonical_bank(checkpoint["shared_bank"]))
        save()
    bank = checkpoint["shared_bank"]
    require(digest(canonical_bank(bank)) == checkpoint["first_round_sha256"], "Frozen first-round checkpoint was modified")
    runs = checkpoint.setdefault("runs", {})
    for variant in VARIANTS:
        if variant in runs:
            continue
        sessions = checkpoint.setdefault("sessions", {})
        if variant not in sessions:
            require(not checkpoint.get("creating_" + variant), "Session creation is uncertain; reconcile it before resuming")
            checkpoint["creating_" + variant] = True
            save()
            sessions[variant] = adapter.create(pair[variant], threshold)
            checkpoint["creating_" + variant] = False
            save()
        session_id = sessions[variant]
        probes = checkpoint.setdefault("probes", {}).setdefault(variant, {})
        if name in {"process_restart", "saved_draft_restore"}:
            record = probes.setdefault("restart", {})
            if not record.get("done"):
                require(not record.get("pending"), "Restart probe outcome is uncertain; reconcile it before resuming")
                record["pending"] = True
                save()
                record.update(adapter.restart_probe(pair[variant], session_id, bank))
                require(record.get("draft_and_questions_restored") is True, "Owned API restart did not preserve the draft/question bank")
                record.update(done=True, pending=False)
                save()
        adapter.clone_first(pair[variant], session_id, bank)
        before = adapter.state(pair[variant], session_id)
        require(before["passing_threshold"] == threshold, "Saved workflow threshold differs from the frozen scenario")
        require(digest(canonical_bank(before["bank"])) == checkpoint["first_round_sha256"], "Paired first-round replay changed questions, answers, grades or feedback")
        run = {"repeat": repeat, "session_id": session_id, "shared_session_id": checkpoint["shared_session"],
               "passing_threshold": before["passing_threshold"],
               "first_round_sha256": checkpoint["first_round_sha256"], "execution_mode": "shared_first_round_replay",
               "actions": ["start_session", "record_saved_threshold_and_question_ids", "submit_first_round", "capture_first_round_grade_and_feedback"],
               "transitions": ["start", "round1_generated", "round1_submitted", "round1_scored"],
               "third_round": False, "duplicate_scoring": False, "qa_score_changed": False,
               "grading_feedback_latency_ms": checkpoint.get("shared_events", {}).get("grading_feedback_latency_ms"),
               "model_calls": None, "input_tokens": None, "output_tokens": None,
               "estimated_cost": None, "observation_status": "completed"}
        if name in {"process_restart", "saved_draft_restore"}:
            run["actions"][2:2] = ["save_partial_answers", "restart_api_process", "resume_same_session", "assert_same_question_ids_and_drafts"]
            run["owned_restart_probe"] = probes["restart"]
        if name == "model_timeout_then_retry":
            fault = checkpoint["shared_events"].get("timeout_probe")
            require(isinstance(fault, dict) and fault.get("saved_draft_without_grade") is True and fault.get("real_retry_completed") is True,
                    "No shared real-controller timeout/retry evidence was recorded")
            run["actions"][2:2] = ["inject_grader_timeout", "submit_answer", "assert_saved_draft_without_official_score",
                                    "restore_grader", "retry_same_submission"]
            run["fault_injected"] = True
            run["fault_scope"] = "shared_first_round_replayed_for_both_systems"
            run["shared_timeout_probe"] = fault
        from agent.telemetry import usage_context
        with usage_context(system=variant):
            adapter.advance(pair[variant], session_id, variant)
        state = adapter.state(pair[variant], session_id)
        def probe_duplicate():
            record = probes.setdefault("duplicate", {})
            if not record.get("done"):
                require(not record.get("pending"), "Duplicate probe outcome is uncertain")
                record["pending"] = True
                original = grade_snapshot(adapter.state(pair[variant], session_id))
                record["before_sha256"] = original
                save()
                with usage_context(system=variant):
                    duplicate = adapter.duplicate(pair[variant], session_id, variant)
                changed = grade_snapshot(adapter.state(pair[variant], session_id)) != original
                require(type(duplicate.get("grading_calls")) is int, "Duplicate-submission grading instrumentation is unavailable")
                record.update(done=True, pending=False, changed=changed or duplicate["grading_calls"] > 0)
                save()
            run["duplicate_scoring"] = record["changed"]
            run["actions"].extend(["repeat_processed_submission_with_changed_response", "assert_original_grade_and_no_extra_grading_call"])

        if name == "duplicate_submit":
            probe_duplicate()
        if name in QA_SCENARIOS:
            record = probes.setdefault("qa", {})
            if not record.get("done"):
                require(not record.get("pending"), "Q&A probe outcome is uncertain; reconcile it before resuming")
                record["pending"] = True
                original = grade_snapshot(state)
                record["before_sha256"] = original
                save()
                with usage_context(system=variant):
                    adapter.ask(pair[variant], selected.get("qa_question"))
                record.update(done=True, pending=False, changed=grade_snapshot(adapter.state(pair[variant], session_id)) != original)
                save()
            run["qa_score_changed"] = record["changed"]
            run["actions"].extend(["snapshot_practice_scores_round_and_status", "ask_independent_question", "assert_practice_snapshot_unchanged"])
        if any(row["round_number"] == 2 for row in state["bank"]):
            require(variant == "full" and state["round_number"] == 2, "Unexpected follow-up round")
            weak = {row["concept_name"] for row in bank if not row["correct"]}
            generated = {row["concept_name"] for row in state["bank"] if row["round_number"] == 2}
            require(generated and generated == weak, "Second round must target exactly the first-round weak concepts")
            run["actions"].append("verify_second_round_targets_only_weak_concepts")
            run["transitions"].append("round2_generated")
            if state["status"] == "open":
                started = time.perf_counter()
                with usage_context(system=variant):
                    adapter.finish_second(pair[variant], session_id, selected)
                second_elapsed = round((time.perf_counter() - started) * 1000)
                first_elapsed = run["grading_feedback_latency_ms"]
                run["grading_feedback_latency_ms"] = first_elapsed + second_elapsed if first_elapsed is not None else None
                run["second_round_grading_feedback_latency_ms"] = second_elapsed
            state = adapter.state(pair[variant], session_id)
            run["actions"].extend(["submit_second_round", "assert_round_scores_separate"])
            run["transitions"].extend(["round2_submitted", "round2_scored"])
        require(state["status"] == "finished" and state.get("report"), "No saved final report was observed")
        require(state["passing_threshold"] == threshold, "Workflow threshold changed during the session")
        if name == "duplicate_after_final":
            probe_duplicate()
        run["actions"].extend(["capture_final_report", "assert_no_automatic_third_round", "reopen_and_verify_saved_result"])
        run["transitions"].append("finished")
        run["round_count"] = max(row["round_number"] for row in state["bank"])
        run["third_round"] = run["round_count"] > (1 if variant == "baseline" else 2)
        saved = grade_snapshot(state)
        adapter.reopen(pair[variant], session_id, variant)
        require(grade_snapshot(adapter.state(pair[variant], session_id)) == saved, "Reopening changed a saved final result")
        rounds = state["round_results"]
        require(rounds and len(rounds) == run["round_count"], "Round scores were not saved separately")
        run["final_state"] = state["report"]["outcome"]
        observed_first = rounds[0]
        requested_first = item.get("scenario", {}).get("round1") or {}
        requested_second = item.get("scenario", {}).get("round2")
        run["scenario_match"] = all(observed_first.get(key + "_count" if key == "correct" else key) == value
                                    for key, value in requested_first.items())
        if requested_second and variant == "full":
            run["scenario_match"] = run["scenario_match"] and len(rounds) == 2 and rounds[-1]["passed"] == (requested_second.get("result") == "pass")
        elif variant == "full":
            run["scenario_match"] = run["scenario_match"] and len(rounds) == 1
        run["observed_rounds"] = rounds
        run["observed_first_round_branch"] = "first_round_pass" if rounds[0]["passed"] else "followup"
        run["response_input_origin"] = "frozen_authored_or_reference_based_test_policy_not_student_data"
        if (item.get("expected") or {}).get(variant, {}).get("policy") == "actual_grade_v1":
            from evaluation.protocol import actual_grade_expectation
            rule = actual_grade_expectation(item, variant, rounds)
            run["scenario_match"] = bool(rule and rule["grade_consistent"])
        if not run["scenario_match"]:
            run["observation_status"] = "mismatch"
        if type(adapter) is MySQLPracticeAdapter:
            run.update(adapter.recorded_usage(item["id"], repeat, variant,
                extra_expected=name in QA_SCENARIOS or (variant == "full" and run["round_count"] == 2)))
        for flag, observed in checkpoint.get("known_prohibited", {}).get(variant, {}).items():
            if observed:
                run[flag] = True
        runs[variant] = run
        save()
    return runs


class MySQLPracticeAdapter:
    """Real model/controller/SQL adapter, restricted to pre-created eval fixtures."""
    synthetic = False

    def __init__(self):
        self.chapters = {}
        self.process = None
        self.process_url = None
        self.frozen_data = self.frozen_manifest = None

    def verify_configuration(self, data, bindings):
        from evaluation.runtime import verify_runtime, load_frozen_manifest
        result = verify_runtime(data, bindings)
        self.frozen_data = data
        self.bindings = bindings
        self.frozen_manifest = load_frozen_manifest(data, bindings["manifest_path"])
        if bindings.get("owned_api_url"):
            from evaluation.integration import local_api_url, OwnedApiProcess
            self.process_url = local_api_url(bindings["owned_api_url"])
            self.process = OwnedApiProcess(self.process_url)
        return result

    def verify_current(self):
        from evaluation.runtime import verify_runtime
        return verify_runtime(self.frozen_data, self.bindings)

    def recorded_usage(self, item_id, repeat, variant, extra_expected):
        import json
        import os
        from pathlib import Path
        from evaluation.core import summarize_usage
        path = Path(os.environ.get("MODEL_USAGE_LOG") or Path(__file__).resolve().parents[1] / "logs/model-usage.jsonl")
        groups = {"shared_first_round": [], variant: []}
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    context = row.get("context") or {}
                    if (context.get("evaluation_id") == self.frozen_data["evaluation_id"] and context.get("item_id") == item_id
                            and context.get("repeat") == repeat and context.get("system") in groups):
                        groups[context["system"]].append(row)
        except (OSError, ValueError, TypeError, AttributeError):
            return {"usage_status": "unknown_journal_unavailable"}
        shared, extra = groups["shared_first_round"], groups[variant]
        result = {"usage_accounting": "shared_first_round_logical_cost_plus_system_specific_calls",
                  "shared_first_round_usage": summarize_usage(shared), "additional_usage": summarize_usage(extra)}
        # The production shared round always contains real short-answer model
        # calls. A follow-up or QA probe also requires a model. Missing callback
        # records for those operations are unknown, never zero-cost successes.
        if not shared or (extra_expected and not extra):
            result["usage_status"] = "unknown_missing_expected_records"
            return result
        combined = summarize_usage([*shared, *extra])
        result.update({field: combined[field]["total"] for field in ("model_calls", "input_tokens", "output_tokens", "estimated_cost")})
        result["cost_currency"] = combined["cost_currency"]
        result["usage_status"] = "recorded"
        return result

    def supports(self, operation):
        return operation == "model_timeout_then_retry" or (operation in {"process_restart", "saved_draft_restore"} and self.process is not None)

    def close(self):
        if self.process is not None:
            self.process.stop()

    @staticmethod
    def identity(fixture):
        return tuple(fixture[field] for field in ("user_id", "course_id", "chapter_id"))

    def validate_pair(self, pair):
        from db.connection import connect
        from db.exams import load_chapter
        signatures = []
        for role in ("shared", *VARIANTS):
            fixture = pair[role]
            user, course, chapter = self.identity(fixture)
            connection = connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT username FROM users WHERE id = %s", (user,))
                    row = cursor.fetchone()
                    require(row and row["username"].startswith("citepath_eval_"), "Only dedicated citepath_eval_ users may be evaluated")
            finally:
                connection.close()
            loaded = load_chapter(user, course, chapter, require_ready=True)
            self.chapters[self.identity(fixture)] = loaded
            signatures.append({"concepts": [c["name"] for c in loaded["concepts"]],
                               "pages": sorted((int(p["page_number"]), digest(str(p["body"]))) for p in loaded["pages"])})
        require(all(value == signatures[0] for value in signatures), "Paired fixtures must have identical concepts and source-page text")

    def validate_case(self, pair, item):
        from db.connection import connect
        documents = [document for document in self.frozen_data["documents"] if document["lecture"] == item["lecture"]]
        require(len(documents) == 1, "One frozen PDF must identify each workflow lecture")
        frozen = documents[0]
        expected_pages = set(frozen["teaching_pages"])
        for role in ("shared", *VARIANTS):
            fixture = pair[role]
            chapter = self.chapters[self.identity(fixture)]
            pages = chapter["pages"]
            identifiers = {int(page["document_id"]) for page in pages}
            require(len(identifiers) == 1 and {int(page["page_number"]) for page in pages} == expected_pages,
                    "Reviewed workflow chapter must cover the complete frozen lecture teaching pages")
            connection = connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT d.content_hash, d.is_active, COUNT(p.id) AS page_count FROM documents d "
                                   "LEFT JOIN pages p ON p.document_id = d.id WHERE d.id = %s AND d.course_id = %s "
                                   "GROUP BY d.id, d.content_hash, d.is_active", (next(iter(identifiers)), fixture["course_id"]))
                    observed = cursor.fetchone()
            finally:
                connection.close()
            require(observed and observed["is_active"] and observed["content_hash"] == frozen["sha256"]
                    and int(observed["page_count"]) == frozen["page_count"], "Workflow fixture PDF differs from the frozen lecture")

    def create(self, fixture, threshold):
        from db.practice import create_session, practice_lock, reset_progress
        from db.connection import connect
        chapter = self.chapters[self.identity(fixture)]
        user, course, chapter_id = self.identity(fixture)
        with practice_lock(user, course, chapter_id):
            connection = connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) AS n FROM practice_sessions WHERE user_id = %s AND course_id = %s AND chapter_id = %s",
                                   (user, course, chapter_id))
                    require(int(cursor.fetchone()["n"]) == 0, "Use fresh evaluation fixtures; existing session history must be retained")
            finally:
                connection.close()
            reset_progress(user, [int(c["id"]) for c in chapter["concepts"]])
            return create_session(user, course, chapter, threshold)

    def prepare_shared(self, fixture, session_id, answers):
        from agent import practice as controller
        from db import practice as storage
        user, course, chapter_id = self.identity(fixture)
        chapter = self.chapters[self.identity(fixture)]
        from agent.telemetry import usage_context
        events = {}
        with storage.practice_lock(user, course, chapter_id), usage_context(system="shared_first_round", user_id=user,
                course_id=course, chapter_id=chapter_id, session_id=session_id):
            if storage.round_question_count(session_id, 1) == 0:
                controller._generate_round(user, course, session_id, chapter, 1, chapter["concepts"])
            started = time.perf_counter()
            while True:
                question = storage.unanswered_question(session_id)
                if question is None:
                    break
                response = response_for(question, answers, 1)
                storage.save_draft(session_id, int(question["id"]), response)
                if answers.get("_inject_shared_timeout") and question["kind"] == "short" and not events:
                    from unittest.mock import patch
                    with patch.object(controller, "_grade_shorts", side_effect=TimeoutError("injected_evaluation_timeout")):
                        try:
                            controller._grade_and_store(user, storage.get_owned_session(user, course, session_id), question, response)
                        except TimeoutError:
                            pass
                        else:
                            raise RuntimeError("The injected grader timeout was not observed")
                    saved = storage.get_owned_session(user, course, session_id)
                    target = storage.question_in_session(session_id, int(question["id"]))
                    require(saved["drafts"].get(str(question["id"])) == response and not saved["round_results"]
                            and target is not None and target["answer_id"] is None,
                            "Timeout created an official grade or lost the saved draft")
                    # The original production grader has now been restored. The
                    # successful actual result is collected once, then replayed.
                    controller._grade_and_store(user, saved, question, response)
                    require(storage.question_in_session(session_id, int(question["id"]))["answer_id"] is not None,
                            "The real grader retry did not persist an answer")
                    events["timeout_probe"] = {"question_id": int(question["id"]), "exception_type": "TimeoutError",
                                               "saved_draft_without_grade": True, "real_retry_completed": True,
                                               "injection_kind": "controller_fault_not_provider_timeout"}
                    continue
                controller._grade_and_store(user, storage.get_owned_session(user, course, session_id), question, response)
        if answers.get("_inject_shared_timeout"):
            require("timeout_probe" in events, "Timeout scenario requires an unanswered short-answer question")
        events["grading_feedback_latency_ms"] = round((time.perf_counter() - started) * 1000)
        return events

    def state(self, fixture, session_id):
        from db import practice as storage
        from db.connection import connect
        from db.feedback import feedback_fields
        user, course, _ = self.identity(fixture)
        session = storage.get_owned_session(user, course, session_id)
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT q.*, a.response, a.correct, a.points_hit, a.points_total,
                    a.rubric_hits_json, a.explanation, a.explanation_status, a.explanation_error, a.explanation_attempts
                    FROM practice_questions q LEFT JOIN practice_answers a ON a.question_id = q.id
                    WHERE q.session_id = %s ORDER BY q.position, q.id""", (session_id,))
                rows = list(cursor.fetchall())
        finally:
            connection.close()
        pages = {(int(p["document_id"]), int(p["page_number"])): digest(str(p["body"]))
                 for p in self.chapters[self.identity(fixture)]["pages"]}
        bank = []
        for row in rows:
            sources = storage._json_list(storage._json_value(row["sources_json"]))
            bank.append({"question_id": int(row["id"]), "round_number": int(row["review_round"]),
                         **{key: row.get(key) for key in ("concept_id", "concept_name", "kind", "prompt", "answer", "response", "points_hit", "points_total")},
                         "correct": None if row["correct"] is None else bool(row["correct"]),
                         "options": storage._json_list(storage._json_value(row["options_json"])),
                         "rubric": storage._json_list(storage._json_value(row["rubric_json"])), "sources": sources,
                         "source_content": [[int(s["page_number"]), pages[(int(s["document_id"]), int(s["page_number"]))]] for s in sources],
                         "rubric_hits": storage._json_list(storage._json_value(row["rubric_hits_json"])) if row["rubric_hits_json"] is not None else None,
                         **feedback_fields(row)})
        return {"status": session["status"], "round_number": int(session["review_round"]),
                "passing_threshold": float(session["passing_threshold"]), "round_results": session["round_results"],
                "report": session["report"], "bank": bank,
                "concepts": self.progress_snapshot(fixture)}

    def progress_snapshot(self, fixture):
        from db.practice import progress_map
        chapter = self.chapters[self.identity(fixture)]
        progress = progress_map(fixture["user_id"], [int(concept["id"]) for concept in chapter["concepts"]])
        return [{"id": int(concept["id"]), "name": concept["name"],
                 "level": int(progress.get(int(concept["id"]), {}).get("level") or 0),
                 "streak": int(progress.get(int(concept["id"]), {}).get("streak") or 0)} for concept in chapter["concepts"]]

    def mapped_questions(self, fixture, bank):
        chapter = self.chapters[self.identity(fixture)]
        concepts = {c["name"]: int(c["id"]) for c in chapter["concepts"]}
        pages = {(int(p["page_number"]), digest(str(p["body"]))): p for p in chapter["pages"]}
        questions = []
        for row in bank:
            require(row["round_number"] == 1 and type(row["correct"]) is bool, "Only fully graded first rounds can be replayed")
            sources = []
            for number, body_hash in row["source_content"]:
                page = pages[(number, body_hash)]
                sources.append({key: page[key] for key in ("document_id", "page_number", "filename")})
            questions.append({**row, "concept_id": concepts[row["concept_name"]], "sources": sources})
        return questions

    def clone_first(self, fixture, session_id, bank):
        from db import practice as storage
        from db.connection import connect
        user, course, chapter_id = self.identity(fixture)
        questions = self.mapped_questions(fixture, bank)
        with storage.practice_lock(user, course, chapter_id):
            storage.store_round(session_id, 1, questions)
            current = self.state(fixture, session_id)["bank"]
            require(len(current) >= len(bank), "Saved first-round bank is incomplete")
            require([{key: r[key] for key in ("prompt", "answer", "rubric", "options", "source_content")} for r in current[:len(bank)]] ==
                    [{key: r[key] for key in ("prompt", "answer", "rubric", "options", "source_content")} for r in bank], "Saved question bank differs from checkpoint")
            for row, target in zip(bank, current):
                if target["correct"] is not None:
                    continue
                storage.save_answer(target["question_id"], row["response"], row["correct"], row["points_hit"], row["points_total"], row["explanation"], row["rubric_hits"])
                connection = connect()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("""UPDATE practice_answers SET explanation_status = %s, explanation_error = %s,
                            explanation_attempts = %s WHERE question_id = %s""",
                                       (row["explanation_status"], row["explanation_error"], row["explanation_attempts"], target["question_id"]))
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

    def restart_probe(self, fixture, session_id, bank):
        import os
        import re
        from db import practice as storage
        from evaluation.integration import ApiClient, practice_snapshot
        from evaluation.runtime import verify_observed_runtime
        require(self.process is not None, "An owned API process is required for restart observation")
        credentials = {}
        for field in ("username", "password"):
            variable = fixture.get(field + "_env")
            require(isinstance(variable, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,99}", variable), "Restart credentials must use environment variable names")
            credentials[field] = os.environ.get(variable, "")
            require(bool(credentials[field]), "Restart test credentials are missing")
        require(credentials["username"].startswith("citepath_eval_"), "Restart requires a dedicated evaluation account")
        user, course, chapter = self.identity(fixture)
        with storage.practice_lock(user, course, chapter):
            storage.store_round(session_id, 1, self.mapped_questions(fixture, bank))
        if self.process.process is None:
            self.process.start()
        client = ApiClient(self.process_url)
        try:
            account = client.request("POST", "/api/login", credentials)
            require(account.get("id") == user and account.get("username") == credentials["username"], "Restart login identity differs from fixture")
            observed = client.request("GET", f"/api/courses/{course}/evaluation/runtime")
            verify_observed_runtime(self.frozen_data, self.frozen_manifest, observed)
            base = f"/api/courses/{course}/practice/{session_id}"
            before = client.request("GET", base)
            question = before.get("question")
            require(before.get("status") == "open" and question is not None, "Restart needs an unanswered persisted question")
            response = next(row["response"] for row in bank if row["prompt"] == question["prompt"] and row["kind"] == question["kind"])
            client.request("PATCH", base + "/draft", {"question_id": question["id"], "response": response})
            saved = client.request("GET", base)
            require(saved["question"]["response"] == response, "API did not persist the draft before restart")
            before_hash = digest(practice_snapshot(saved))
            self.process.restart()
            restored = client.request("GET", base)
            after_hash = digest(practice_snapshot(restored))
            require(before_hash == after_hash and restored["question"]["id"] == question["id"], "Restart changed persisted questions, draft, grades or status")
            return {"draft_and_questions_restored": True, "before_sha256": before_hash,
                    "after_sha256": after_hash, "question_id": question["id"], "process_owned_by_collector": True}
        finally:
            try:
                client.request("POST", "/api/logout")
            except Exception:
                pass

    def advance(self, fixture, session_id, variant):
        from agent import practice as controller
        from db import practice as storage
        from agent.report_text import enrich_report
        user, course, chapter_id = self.identity(fixture)
        if variant == "full":
            controller.open_practice(user, course, session_id)
            return
        with storage.practice_lock(user, course, chapter_id):
            session = storage.get_owned_session(user, course, session_id)
            if session["status"] == "finished":
                return
            attempts = storage.load_session_attempts(session_id)
            require(attempts and all(a["round_number"] == 1 for a in attempts), "Baseline must have exactly one graded round")
            result = controller.round_result(attempts, 1, session["passing_threshold"])
            storage.save_round_results(session_id, [result])
            controller._sync_progress(user, attempts)
            report = controller.build_practice_report(self.chapters[self.identity(fixture)]["concepts"], {}, attempts)
            report.update({"rounds": [result], "passed": result["passed"], "passing_threshold": float(session["passing_threshold"]),
                           "outcome": "passed" if result["passed"] else "failed", "evaluation_baseline": True,
                           "remaining_weak_concepts": result["weak_concepts"], "remaining_sources": []})
            storage.publish_session_report(session_id, enrich_report(report), closing=True)

    def finish_second(self, fixture, session_id, answers):
        from agent import practice as controller
        from db import practice as storage
        user, course, _ = self.identity(fixture)
        for _ in range(80):
            state = self.state(fixture, session_id)
            if state["status"] == "finished":
                return
            require(state["round_number"] == 2, "Only one targeted follow-up round is allowed")
            question = storage.unanswered_question(session_id)
            require(question is not None, "An open second round has no question")
            controller.answer_practice(user, course, session_id, int(question["id"]), response_for(question, answers, 2))
        raise RuntimeError("Second-round answer limit exceeded")

    def duplicate(self, fixture, session_id, variant):
        # A finished baseline cannot enter production's two-round controller.
        from agent import practice as controller
        from db import practice as storage
        user, course, _ = self.identity(fixture)
        first = self.state(fixture, session_id)["bank"][0]
        before = self.grading_calls(session_id)
        changed = "D" if first["kind"] == "mcq" and first["response"] != "D" else "A" if first["kind"] == "mcq" else "An altered repeated response"
        if variant == "baseline":
            self.submit_baseline(fixture, session_id, first["question_id"], changed)
        else:
            controller.answer_practice(user, course, session_id, first["question_id"], changed)
        after = self.grading_calls(session_id)
        return {"grading_calls": after - before if before is not None and after is not None else None}

    def submit_baseline(self, fixture, session_id, question_id, response):
        from db import practice as storage
        user, course, chapter = self.identity(fixture)
        require(isinstance(response, str) and len(response) <= 5000, "Invalid baseline response")
        with storage.practice_lock(user, course, chapter):
            session = storage.get_owned_session(user, course, session_id)
            require(session["status"] == "finished" and (session.get("report") or {}).get("evaluation_baseline"),
                    "Baseline submission needs a saved one-round evaluation report")
            question = storage.question_in_session(session_id, question_id)
            require(question is not None and question["answer_id"] is not None, "Repeated baseline response has no saved answer")
            return self.state(fixture, session_id)

    @staticmethod
    def grading_calls(session_id):
        import json
        import os
        from pathlib import Path
        path = Path(os.environ.get("OPERATION_LOG") or Path(__file__).resolve().parents[1] / "logs" / "operations.jsonl")
        if not path.exists():
            return None
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                context = json.loads(line).get("context") or {}
            except (ValueError, AttributeError):
                continue
            count += context.get("operation") == "practice.grade" and context.get("session_id") == session_id
        return count

    def ask(self, fixture, question):
        from agent.qa import answer_question
        require(isinstance(question, str) and question.strip(), "Q&A scenario needs a recorded independent question")
        user, course, _ = self.identity(fixture)
        answer_question(user, course, question)

    def reopen(self, fixture, session_id, variant):
        if variant == "full":
            from agent.practice import open_practice
            user, course, _ = self.identity(fixture)
            open_practice(user, course, session_id)
        else:
            self.state(fixture, session_id)
