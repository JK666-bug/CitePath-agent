import json
import unittest
from unittest.mock import MagicMock, patch

from db.courses import update_course_settings
from agent.chapterization import rebuild_chapters


class CourseSettingsTests(unittest.TestCase):
    def test_update_preserves_existing_schedule_and_deduplicates_events(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"student_brief": json.dumps({"schema": "citepath-course-v1", "scheduling_profile": {"daily_minutes": 60}})}
        with patch('db.courses.connect', return_value=connection):
            update_course_settings(7, 9, ' Course ', 'Note', '', 0, [
                {'title': 'Exam', 'date': '2026-12-11'},
                {'title': 'Exam', 'date': '2026-12-11'},
            ], '2026-11-21')
        sql, args = cursor.execute.call_args_list[1].args
        self.assertIn('user_id=%s', sql)
        brief = json.loads(args[1])
        self.assertEqual(brief['scheduling_profile']['daily_minutes'], 60)
        self.assertEqual(brief['startDate'], '2026-11-21')
        self.assertEqual(brief['events'], [{'title': 'Exam', 'date': '2026-12-11'}])
        connection.commit.assert_called_once()

    def test_cannot_change_another_users_course(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with patch('db.courses.connect', return_value=connection):
            with self.assertRaises(LookupError):
                update_course_settings(7, 9, 'Course', '', '', 0, [])
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_chapterizer_uses_temporary_date_without_mutating_stored_brief(self):
        brief = json.dumps({'schema': 'citepath-course-v1', 'deadline': '', 'earlyDays': 0, 'note': 'test'})
        state = {'token': 'token', 'brief': brief, 'documents': [], 'pages': [{'document_id': 3}]}
        with patch('agent.chapterization.prepare_chapterization', return_value=state), \
             patch('agent.chapterization.choose_documents', return_value=[3]), \
             patch('agent.chapterization._split_pages', return_value=([], 'reason')) as split, \
             patch('agent.chapterization.save_document_chapters', return_value={'ok': True}):
            rebuild_chapters(7, 9, 'token', [3], False)
        self.assertTrue(split.call_args.args[0]['deadline'])
        self.assertEqual(json.loads(state['brief'])['deadline'], '')


if __name__ == '__main__':
    unittest.main()
