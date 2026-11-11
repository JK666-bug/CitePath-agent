import json
import unittest
from unittest.mock import patch

from agent.plan import (
    assemble_plan,
    chapters_from_reply,
    parse_brief,
    schedule_tasks,
    study_window,
    _split_pages,
)
from db.courses import brief_with_note


def _page(document_id, number, chapter, filename="notes.pdf"):
    return {
        "document_id": document_id,
        "filename": filename,
        "page_number": number,
        "body": f"{chapter} page {number}",
    }


class StudyWindowTest(unittest.TestCase):
    def test_keeps_an_ordered_date_range(self):
        self.assertEqual(
            study_window("2026-11-08", "2026-12-01"),
            ("2026-11-08", "2026-12-01"),
        )

    def test_rejects_an_end_before_the_start(self):
        with self.assertRaises(ValueError):
            study_window("2026-12-01", "2026-11-08")


class BriefNoteTest(unittest.TestCase):
    def test_replaces_only_the_note(self):
        updated = brief_with_note(
            json.dumps(
                {
                    "schema": "citepath-course-v1",
                    "deadline": "2026-12-08",
                    "earlyDays": 2,
                    "note": "beginner",
                }
            ),
            "I want a high score",
        )
        stored = json.loads(updated)
        self.assertEqual(stored["note"], "I want a high score")
        self.assertEqual(stored["deadline"], "2026-12-08")
        self.assertEqual(stored["earlyDays"], 2)


class ParseBriefTest(unittest.TestCase):
    def test_reads_goal_level_and_dates(self):
        brief = parse_brief(
            json.dumps(
                {
                    "schema": "citepath-course-v1",
                    "deadline": "2026-12-08",
                    "earlyDays": 2,
                    "note": "beginner, I want a high score",
                }
            )
        )

        self.assertEqual(brief["deadline"], "2026-12-08")
        self.assertEqual(brief["early_days"], 2)
        self.assertNotIn("weekly_hours", brief)
        self.assertIn("beginner", brief["note"])

    def test_rejects_a_plain_note_without_dates(self):
        with self.assertRaises(ValueError):
            parse_brief("I am a beginner")


class PlanBuildTest(unittest.TestCase):
    def setUp(self):
        self.pages = [
            _page(1, 1, "Trees"),
            _page(1, 2, "Trees"),
            _page(1, 3, "Graphs"),
        ]

    def test_keeps_only_real_pages_and_requires_full_coverage(self):
        chapters, reason, complete = chapters_from_reply(
            {
                "reason": "A beginner should meet trees before graphs.",
                "chapters": [
                    {
                        "title": "Trees",
                        "concepts": ["Binary tree", "Traversal"],
                        "pages": [
                            {"document_id": 1, "page_number": 1},
                            {"document_id": 1, "page_number": 2},
                            {"document_id": 9, "page_number": 9},
                        ],
                    }
                ],
            },
            self.pages,
        )

        self.assertFalse(complete)
        self.assertEqual([item["title"] for item in chapters], ["Trees"])
        self.assertEqual(chapters[0]["concepts"], ["Binary tree", "Traversal"])
        self.assertEqual(
            [item["page_number"] for item in chapters[0]["sources"]],
            [1, 2],
        )
        self.assertIn("beginner", reason)

    def test_accepts_a_split_that_places_every_page(self):
        chapters, _reason, complete = chapters_from_reply(
            {
                "reason": "Trees come before graphs.",
                "chapters": [
                    {
                        "title": "Trees",
                        "concepts": ["Binary tree", "Traversal"],
                        "pages": [
                            {"document_id": 1, "page_number": 1},
                            {"document_id": 1, "page_number": 2},
                        ],
                    },
                    {
                        "title": "Graphs",
                        "concepts": ["Search", "Queue"],
                        "pages": [{"document_id": 1, "page_number": 3}],
                    },
                ],
            },
            self.pages,
        )

        self.assertTrue(complete)
        self.assertEqual([item["title"] for item in chapters], ["Trees", "Graphs"])

    def test_ignores_a_page_claimed_twice(self):
        chapters, _reason, complete = chapters_from_reply(
            {
                "reason": "Start with the first section.",
                "chapters": [
                    {
                        "title": "First",
                        "concepts": ["Root", "Leaf"],
                        "pages": [{"document_id": 1, "page_number": 1}],
                    },
                    {
                        "title": "Again",
                        "concepts": ["Root", "Leaf"],
                        "pages": [{"document_id": 1, "page_number": 1}],
                    },
                ],
            },
            self.pages,
        )

        self.assertFalse(complete)
        self.assertEqual(chapters[0]["title"], "First")
        self.assertNotIn("Again", [item["title"] for item in chapters])

    def test_accepts_more_than_twelve_chapters_without_losing_pages(self):
        pages = [_page(1, number, "Topic") for number in range(1, 18)]
        payload = _proposal(pages)
        chapters, _, complete = chapters_from_reply(payload, pages)
        self.assertTrue(complete)
        self.assertEqual(len(chapters), 17)
        self.assertEqual(chapters[-1]["sources"][0]["page_number"], 17)

    def test_schedule_places_chapters_on_dates_only(self):
        chapters = [
            {
                "id": "c1",
                "title": "Trees",
                "concepts": ["Binary tree", "Traversal"],
                "sources": [
                    {"document_id": 1, "filename": "notes.pdf", "page_number": 1},
                    {"document_id": 1, "filename": "notes.pdf", "page_number": 2},
                ],
            },
            {
                "id": "c2",
                "title": "Graphs",
                "concepts": ["Search", "Queue"],
                "sources": [
                    {"document_id": 1, "filename": "notes.pdf", "page_number": 3},
                ],
            },
        ]
        plan = assemble_plan(
            chapters,
            "2026-11-08",
            "2026-11-10",
            "Keep the pace steady.",
            1,
        )

        self.assertEqual(plan["start"], "2026-11-08")
        self.assertEqual(plan["end"], "2026-11-10")
        self.assertEqual(
            [task["date"] for task in plan["tasks"]],
            [
                "2026-11-08",
                "2026-11-08",
                "2026-11-08",
                "2026-11-10",
                "2026-11-10",
                "2026-11-10",
            ],
        )
        self.assertNotIn("minutes", plan["tasks"][0])
        self.assertEqual(
            schedule_tasks(chapters, "2026-11-08", "2026-11-10")[0]["date"],
            "2026-11-08",
        )


def _proposal(pages):
    return {
        "reason": "Follow the document's learning objectives.",
        "chapters": [
            {
                "title": f"Topic {page['document_id']}-{page['page_number']}",
                "concepts": ["Definition", "Application"],
                "pages": [{"document_id": page["document_id"], "page_number": page["page_number"]}],
            }
            for page in pages
        ],
    }


class DocumentDivisionTest(unittest.TestCase):
    @patch("agent.plan._ask_model")
    def test_divides_documents_in_isolation_and_schedules_every_chapter(self, ask):
        first = [_page(1, number, "First") for number in range(1, 10)]
        second = [_page(2, number, "Second", "other.pdf") for number in range(1, 9)]
        ask.side_effect = lambda brief, pages, start, end, remind: _proposal(pages)
        args = ({"note": "Beginner"}, "2026-11-11", "2026-12-09")
        alone, _ = _split_pages(args[0], first, *args[1:])
        ask.reset_mock()
        combined, _ = _split_pages(args[0], first + second, *args[1:])
        self.assertEqual(combined[:len(alone)], alone)
        self.assertEqual([call.args[1] for call in ask.call_args_list], [first, second])
        self.assertEqual([chapter["id"] for chapter in combined], [f"c{i}" for i in range(1, 18)])
        plan = assemble_plan(combined, *args[1:], "Per-document division", 1)
        self.assertEqual(len({task["id"] for task in plan["tasks"]}), 51)

    @patch("agent.plan._ask_model")
    def test_retries_only_the_incomplete_document(self, ask):
        first = [_page(1, 1, "First")]
        second = [_page(2, 1, "Second", "other.pdf")]
        # A reference to another document cannot satisfy this document's coverage.
        ask.side_effect = [_proposal(first), _proposal(first), _proposal(second)]
        chapters, _ = _split_pages({"note": "Learn"}, first + second, "2026-11-11", "2026-12-09")
        self.assertEqual(len(chapters), 2)
        self.assertEqual([call.args[1] for call in ask.call_args_list], [first, second, second])
        self.assertEqual([call.kwargs["remind"] for call in ask.call_args_list], [False, False, True])

    @patch("agent.plan._ask_model")
    def test_does_not_return_a_partial_course_when_a_document_fails(self, ask):
        first = [_page(1, 1, "First")]
        second = [_page(2, 1, "Second", "other.pdf")]
        ask.side_effect = [_proposal(first), None, None]
        with self.assertRaisesRegex(ValueError, "Could not divide"):
            _split_pages({"note": "Learn"}, first + second, "2026-11-11", "2026-12-09")
