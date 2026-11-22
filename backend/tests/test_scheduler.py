import copy
import unittest
from datetime import date, timedelta

from agent.learning_tasks import chapter_task, ensure_chapter_tasks
from agent.scheduler import estimate_times, propose_schedule, requirements, today, validate_schedule


def fixture():
    plan, _ = ensure_chapter_tasks({"version": 2, "chapters": [
        {"id": "4", "title": "A", "concepts": ["a", "b"], "sources": []},
        {"id": "5", "title": "B", "concepts": ["c"], "sources": []},
    ], "tasks": []})
    end = (date.fromisoformat(today()) + timedelta(days=14)).isoformat()
    profile = requirements({"daily_minutes": 10, "end": end}, {"deadline": end})
    return plan, profile


class SchedulingTest(unittest.TestCase):
    def test_tasks_exist_without_dates_and_repair_is_idempotent(self):
        plan, _ = fixture()
        self.assertEqual(len(plan["tasks"]), 4)
        self.assertTrue(all(not t["date"] for t in plan["tasks"]))
        old = copy.deepcopy(plan)
        repaired, count = ensure_chapter_tasks(plan)
        self.assertEqual(count, 0)
        self.assertEqual(repaired, old)
        self.assertEqual(plan, old)

    def test_split_sessions_respect_capacity_and_do_not_copy_tasks(self):
        plan, profile = fixture()
        estimates = estimate_times(plan, {}, {})
        candidate = propose_schedule(plan, profile, estimates, {})
        self.assertTrue(validate_schedule(plan, profile, estimates, candidate)["valid"])
        self.assertGreater(len(candidate["slots"]), len(plan["tasks"]))
        self.assertEqual(len(plan["tasks"]), 4)

    def test_practice_does_not_precede_completion_of_reading(self):
        plan, profile = fixture()
        estimates = estimate_times(plan, {}, {})
        estimates["reading-4"]["minutes"] = 25
        candidate = propose_schedule(plan, profile, estimates, {}, "new_first")
        reading = [s["date"] for s in candidate["slots"] if s["task_id"] == "reading-4"]
        practice = [s["date"] for s in candidate["slots"] if s["task_id"] == "practice-4"]
        self.assertGreaterEqual(min(practice), max(reading))
        self.assertTrue(validate_schedule(plan, profile, estimates, candidate)["valid"])

    def test_completed_task_is_not_rescheduled(self):
        plan, profile = fixture()
        plan["tasks"][0].update(status="Completed", date="2026-01-01", completion_source="student")
        estimates = estimate_times(plan, {}, {})
        candidate = propose_schedule(plan, profile, estimates, {})
        self.assertNotIn(plan["tasks"][0]["id"], {s["task_id"] for s in candidate["slots"]})
        self.assertEqual(plan["tasks"][0]["date"], "2026-01-01")

    def test_infeasible_schedule_is_not_valid(self):
        plan, profile = fixture()
        profile.update(end=profile["start"], daily_minutes=1)
        estimates = estimate_times(plan, {}, {})
        candidate = propose_schedule(plan, profile, estimates, {})
        self.assertFalse(validate_schedule(plan, profile, estimates, candidate)["valid"])
        self.assertTrue(candidate["unallocated"])

    def test_off_dates_and_weekdays(self):
        plan, profile = fixture()
        profile.update(daily_minutes=100, weekdays=[0, 1, 2, 3, 4], off_dates=[profile["start"]])
        estimates = estimate_times(plan, {}, {})
        candidate = propose_schedule(plan, profile, estimates, {})
        for slot in candidate["slots"]:
            self.assertNotEqual(slot["date"], profile["start"])
            self.assertLess(date.fromisoformat(slot["date"]).weekday(), 5)

    def test_priorities_and_new_first(self):
        plan, profile = fixture()
        # Chapter A has a Review because its exam was unsuccessful.
        plan["tasks"].append(chapter_task(plan["chapters"][0], "Review"))
        estimates = estimate_times(plan, {}, {})
        profile["priority_chapter_ids"] = ["5"]
        candidate = propose_schedule(plan, profile, estimates, {})
        self.assertEqual(candidate["slots"][0]["task_id"], "reading-5")
        profile["priority_chapter_ids"] = []
        candidate = propose_schedule(plan, profile, estimates, {}, "new_first")
        keys = [s["task_id"] for s in candidate["slots"]]
        self.assertGreater(keys.index("review-4"), keys.index("reading-5"))

    def test_weak_first_distinguishes_mastery_from_historical_mistakes(self):
        plan, profile = fixture()
        plan["chapters"].append({"id": "6", "title": "C", "concepts": ["d"], "sources": []})
        plan, _ = ensure_chapter_tasks(plan)
        reports = {
            "4": {"practice": {"wrong_count": 3, "concepts": [{"attempts": 4, "level": 0}]},
                  "mastery": {"mastered": 2, "attempted": 2}},
            "5": {"mastery": {"mastered": 0, "attempted": 1}},
            "6": {"exam": {"passed": False}, "mastery": {"mastered": 1, "attempted": 1}},
        }
        estimates = estimate_times(plan, {}, reports)
        candidate = propose_schedule(plan, profile, estimates, reports, "weak_first")
        self.assertEqual(candidate["weak_chapters"], {"5": "practice_gaps", "6": "exam_not_passed"})
        ranked = list(dict.fromkeys(slot["task_id"].split("-")[-1] for slot in candidate["slots"]))
        self.assertEqual(ranked, ["6", "5", "4"])
        profile["priority_chapter_ids"] = ["4"]
        candidate = propose_schedule(plan, profile, estimates, reports, "weak_first")
        self.assertEqual(candidate["slots"][0]["task_id"], "reading-4")
        self.assertTrue(validate_schedule(plan, profile, estimates, candidate)["valid"])

    def test_validator_rejects_unknown_tasks_and_capacity_overflow(self):
        plan, profile = fixture()
        estimates = estimate_times(plan, {}, {})
        candidate = propose_schedule(plan, profile, estimates, {})
        candidate["slots"].append({"task_id": "invented", "date": profile["start"], "minutes": 100})
        self.assertFalse(validate_schedule(plan, profile, estimates, candidate)["valid"])

    def test_bad_inputs_do_not_get_silent_defaults(self):
        _, profile = fixture()
        for minutes in (True, 0, -1, 2000):
            with self.assertRaises(ValueError):
                requirements({**profile, "daily_minutes": minutes}, {"deadline": profile["end"]})


if __name__ == "__main__":
    unittest.main()
