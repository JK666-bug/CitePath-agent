"""Upstream preferences/document selection must preserve saved workflow guarantees."""
import copy
import unittest
from contextlib import ExitStack, nullcontext
from datetime import date
from unittest.mock import patch

from agent import exam, plan, practice
from tests.test_planning_workflow import BRIEF, PROFILE, materials
from tests.test_plan_reschedule import sample_plan
from tests.test_practice_rounds import PracticeMemory


class PracticePreferenceWorkflowTest(unittest.TestCase):
    def test_prefs_survive_resume_and_round_two_without_changing_saved_pass_mark(self):
        memory = PracticeMemory(concept_count=2)
        prefs = {"difficulty": "hard", "requirements": "Use concise questions"}
        with ExitStack() as stack:
            mocks = memory.patches(stack)
            normalize = stack.enter_context(patch.object(practice, "normalize_practice_prefs", return_value=prefs))
            practice.start_practice(1, 2, 3, .7, prefs=prefs)
            original_questions = copy.deepcopy(memory.questions)
            resumed = practice.start_practice(1, 2, 3, .9, prefs={"difficulty": "easy"})
            self.assertEqual(float(resumed["passing_threshold"]), .7)
            self.assertEqual(resumed["prefs"], prefs)
            self.assertEqual(memory.questions, original_questions)
            normalize.assert_called_once()
            memory.answer_round([False, False, True, True])
            self.assertEqual(memory.session["review_round"], 2)
            self.assertEqual(len(memory.questions), 6)
            for call in mocks["_write_question"].call_args_list:
                self.assertEqual(call.kwargs, {"prefs": prefs, "course_id": 2})
            memory.answer_round([True, True])
            self.assertEqual(memory.session["report"]["outcome"], "passed_round_2")
            self.assertEqual(len(memory.session["report"]["rounds"]), 2)

    def test_case_answers_do_not_turn_a_missing_grade_into_a_wrong_answer(self):
        question = {"id": 7, "kind": "short", "rubric_json": ["a", "b", "c"]}
        session = {"id": 9, "course_id": 2, "prefs": {"similar_to_cases": True}}
        with patch.object(practice, "_case_answer_text", return_value="Reference answer") as reference, \
                patch.object(practice, "_grade_shorts", return_value={}) as grade, \
                patch.object(practice, "save_answer") as save:
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                practice._grade_and_store(1, session, question, "response")
        reference.assert_called_once_with(2, session["prefs"])
        self.assertEqual(grade.call_args.kwargs, {"case_answers": "Reference answer"})
        save.assert_not_called()


class CaseAnswerGradeValidationTest(unittest.TestCase):
    def test_reference_pages_are_included_but_complete_grades_are_still_required(self):
        shorts = [({"id": 7}, "response", ["a", "b", "c"])]
        with patch.object(exam, "_ask", return_value={"grades": []}) as ask:
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                exam._grade_shorts(shorts, "[case-answer.pdf page 1] Ground truth")
        self.assertIn("Ground truth", ask.call_args.args[1])


class SelectedPlanningWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.course = {"id": 3, "documents": [
            {"id": 7, "kind": "lecture", "is_active": True, "ingest_status": "complete", "usable_page_count": 2},
            {"id": 8, "kind": "lecture", "is_active": True, "ingest_status": "complete", "usable_page_count": 1},
            {"id": 9, "kind": "exam_case", "is_active": True, "ingest_status": "complete", "usable_page_count": 1},
            {"id": 10, "kind": "lecture", "is_active": False, "ingest_status": "complete", "usable_page_count": 1},
        ]}

    def bindings(self, stack, previous=None):
        stack.enter_context(patch.object(plan, "get_course", return_value=self.course))
        stack.enter_context(patch.object(plan, "get_plan", return_value={"plan": previous}))
        stack.enter_context(patch.object(plan, "planning_lock", return_value=nullcontext()))
        stack.enter_context(patch.object(plan, "load_planning_materials", return_value=materials()))
        stack.enter_context(patch.object(plan, "save_course_note", return_value=BRIEF))

    def test_selection_excludes_archived_and_sample_documents(self):
        self.assertEqual(plan._selected_document_ids(self.course, None), [7, 8])
        for selection in ([], [9], [10], [True], ["7"]):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                plan._selected_document_ids(self.course, selection)

    def test_initial_plan_uses_selected_pages_and_full_material_concurrency_guard(self):
        pages = [materials()["pages"][-1]]
        chapter = {"id": "c1", "title": "Graph traversal", "concepts": ["Graph", "Traversal"],
                   "sources": [{"document_id": 8, "page_number": 1, "filename": "new.pdf"}]}
        with ExitStack() as stack:
            self.bindings(stack)
            load = stack.enter_context(patch.object(plan, "load_usable_pages", return_value=pages))
            split = stack.enter_context(patch.object(plan, "_split_pages", return_value=([chapter], "Selected")))
            save = stack.enter_context(patch.object(plan, "save_generated_plan", side_effect=lambda _, p, **kw: p))
            result = plan.generate_plan(1, 3, "2026-11-19", "2026-11-23", "", PROFILE,
                                        expected_version=0, document_ids=[8])
        load.assert_called_once_with(3, document_ids=[8])
        self.assertEqual(split.call_args.args[1], pages)
        self.assertEqual(result["plan"]["document_ids"], [8])
        self.assertEqual(save.call_args.kwargs, {"expected_version": 0, "material_fingerprint": "frozen-materials"})

    def test_selected_append_preserves_old_chapters_and_completed_task(self):
        previous = sample_plan()
        previous["tasks"][0]["status"] = "Completed"
        before = copy.deepcopy(previous)
        pages = [materials()["pages"][-1]]
        chapter = {"id": "c1", "title": "New topic", "concepts": ["Graph", "Traversal"],
                   "sources": [{"document_id": 8, "page_number": 1, "filename": "new.pdf"}]}
        with ExitStack() as stack:
            self.bindings(stack, previous)
            stack.enter_context(patch.object(plan, "load_plan_feedback", return_value={}))
            load = stack.enter_context(patch.object(plan, "load_usable_pages", return_value=pages))
            split = stack.enter_context(patch.object(plan, "_split_pages", return_value=([chapter], "Selected")))
            stack.enter_context(patch.object(plan, "save_appended_plan", side_effect=lambda _, p, ids, **kw: p))
            result = plan.generate_plan(1, 3, "2026-11-19", "2026-11-23", "", PROFILE,
                                        update_materials=True, expected_version=1, document_ids=[8])
        load.assert_called_once_with(3, document_ids=[8])
        self.assertEqual(split.call_args.args[1], pages)
        self.assertEqual(previous, before)
        self.assertEqual(result["plan"]["chapters"][:2][0]["id"], "11")
        self.assertEqual(result["plan"]["document_ids"], [7, 8])
        self.assertEqual(result["plan"]["tasks"][0], before["tasks"][0])

    def test_selecting_all_pdfs_does_not_append_without_explicit_material_update(self):
        previous = sample_plan()
        previous["document_ids"] = [7]
        with ExitStack() as stack:
            self.bindings(stack, previous)
            stack.enter_context(patch.object(plan, "load_plan_feedback", return_value={}))
            load = stack.enter_context(patch.object(plan, "load_usable_pages"))
            split = stack.enter_context(patch.object(plan, "_split_pages"))
            append = stack.enter_context(patch.object(plan, "save_appended_plan"))
            stack.enter_context(patch.object(plan, "save_rescheduled_plan", side_effect=lambda _, p, **kw: p))
            result = plan.generate_plan(1, 3, "2026-11-19", "2026-11-23", "", PROFILE,
                                        update_materials=False, expected_version=1, document_ids=[7, 8])
        load.assert_not_called()
        split.assert_not_called()
        append.assert_not_called()
        self.assertEqual(len(result["plan"]["chapters"]), len(previous["chapters"]))
        for actual, original in zip(result["plan"]["chapters"], previous["chapters"]):
            self.assertEqual({key: actual[key] for key in original}, original)
        self.assertTrue(result["material_update"]["can_update"])
        self.assertEqual(result["plan"]["document_ids"], [7])

    def test_archived_materials_do_not_block_pure_reschedule_with_empty_selection(self):
        previous = sample_plan()
        previous["document_ids"] = [7]
        for selection in (None, [], [999]):
            with self.subTest(selection=selection), ExitStack() as stack:
                self.bindings(stack, previous)
                stack.enter_context(patch.object(plan, "get_course", return_value={"id": 3, "documents": []}))
                stack.enter_context(patch.object(plan, "load_planning_materials", return_value={
                    "pages": [], "documents": [], "fingerprint": "archived",
                }))
                stack.enter_context(patch.object(plan, "load_plan_feedback", return_value={}))
                load = stack.enter_context(patch.object(plan, "load_usable_pages"))
                split = stack.enter_context(patch.object(plan, "_split_pages"))
                stack.enter_context(patch.object(plan, "save_rescheduled_plan", side_effect=lambda _, p, **kw: p))
                result = plan.generate_plan(1, 3, "2026-11-19", "2026-11-23", "", PROFILE,
                                            expected_version=1, document_ids=selection)
                self.assertEqual(result["plan"]["document_ids"], [7])
                self.assertEqual(result["plan"]["chapters"][0]["sources"], previous["chapters"][0]["sources"])
                self.assertEqual(result["plan"]["version"], 2)
                load.assert_not_called()
                split.assert_not_called()

    def test_reschedule_skips_weekends_without_moving_completed_work(self):
        previous = sample_plan()
        previous["tasks"][0].update(status="Completed", date="2026-11-14")
        result = plan.reschedule_plan(previous, "2026-11-13", "2026-11-16", "weekdays only", {})
        self.assertEqual(result["tasks"][0]["date"], "2026-11-14")
        for task in result["tasks"][1:]:
            self.assertLess(date.fromisoformat(task["date"]).weekday(), 5)


if __name__ == "__main__":
    unittest.main()
