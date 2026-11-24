import io
from datetime import datetime, timezone
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock

from academic_assistant.database import LATEST_VERSION, migrate, schema_version
from academic_assistant.integrations.canvas import CanvasClient


def response(items, link=None):
    body = io.BytesIO(json.dumps(items).encode())
    body.headers = Message()
    if link:
        body.headers["Link"] = link
    return body


class MigrationTests(unittest.TestCase):
    def test_migration_creates_database_and_can_run_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance" / "local.sqlite3"
            migrate(path)
            migrate(path)
            self.assertEqual(schema_version(path), LATEST_VERSION)
            self.assertEqual(LATEST_VERSION, 2)

    def test_schema_check_rejects_missing_migration_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.sqlite3"
            migrate(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("DELETE FROM schema_migrations")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "missing schema version"):
                schema_version(path)

    def test_upgrades_version_1_database_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    """CREATE TABLE schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (1, 'v1-marker')")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "Unsupported"):
                schema_version(path)
            migrate(path)
            migrate(path)
            self.assertEqual(schema_version(path), 2)
            with closing(sqlite3.connect(path)) as connection:
                versions = connection.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall()
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertEqual([v for v, _ in versions], [1, 2])
            self.assertEqual(versions[0][1], "v1-marker")
            self.assertLessEqual({"canvas_courses", "canvas_items", "canvas_notifications", "canvas_state"}, tables)

    def test_items_are_unique_by_kind_and_source_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.sqlite3"
            migrate(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("INSERT INTO canvas_courses (id, name) VALUES (1, 'C')")
                insert = (
                    "INSERT INTO canvas_items (kind, source_id, course_id, title, first_seen_at, updated_at)"
                    " VALUES (?, 7, 1, 't', 'x', 'x')"
                )
                connection.execute(insert, ("assignment",))
                connection.execute(insert, ("announcement",))
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(insert, ("assignment",))

    def test_schema_check_rejects_unknown_future_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.sqlite3"
            migrate(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("INSERT INTO schema_migrations (version) VALUES (99)")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "Unsupported"):
                schema_version(path)


class CanvasTests(unittest.TestCase):
    def setUp(self):
        self.client = CanvasClient("https://canvas.example.edu", "fixture-token")
        self.client.opener = Mock()

    def test_follows_next_page_and_authenticates_each_request(self):
        first_page = response([{"id": 1}], '</api/v1/courses/9/assignments?page=1>; rel="current"')
        first_page.headers["Link"] = '</api/v1/courses/9/assignments?page=2>; rel="next"'
        self.client.opener.open.side_effect = [first_page, response([{"id": 2}])]
        self.assertEqual(list(self.client.assignments(9)), [{"id": 1}, {"id": 2}])
        first, second = [call.args[0] for call in self.client.opener.open.call_args_list]
        self.assertEqual(first.full_url, "https://canvas.example.edu/api/v1/courses/9/assignments?per_page=100")
        self.assertEqual(second.full_url, "https://canvas.example.edu/api/v1/courses/9/assignments?page=2")
        self.assertEqual(first.get_header("Authorization"), "Bearer fixture-token")
        self.assertEqual(second.get_header("Authorization"), "Bearer fixture-token")

    def test_does_not_send_token_to_cross_origin_pagination(self):
        self.client.opener.open.return_value = response([], '<https://elsewhere.example/api/v1/a>; rel="next"')
        with self.assertRaisesRegex(ValueError, "Invalid Canvas pagination URL"):
            list(self.client.assignments(9))
        self.client.opener.open.assert_called_once()

    def test_rejects_unexpected_canvas_response(self):
        self.client.opener.open.return_value = response({"errors": []})
        with self.assertRaisesRegex(ValueError, "unexpected assignments response"):
            list(self.client.assignments(9))

    def test_assignments_with_submission_paginates(self):
        first_page = response([{"id": 1}], '<https://canvas.example.edu/api/v1/courses/9/assignments?page=2&include[]=submission>; rel="next"')
        self.client.opener.open.side_effect = [first_page, response([{"id": 2}])]
        self.assertEqual(list(self.client.assignments(9, include_submission=True)), [{"id": 1}, {"id": 2}])
        urls = [call.args[0].full_url for call in self.client.opener.open.call_args_list]
        self.assertEqual(urls, [
            "https://canvas.example.edu/api/v1/courses/9/assignments?per_page=100&include[]=submission",
            "https://canvas.example.edu/api/v1/courses/9/assignments?page=2&include[]=submission",
        ])

    def test_courses_paginates_active_enrollments(self):
        first_page = response([{"id": 1, "name": "A"}], '</api/v1/courses?page=2&enrollment_state=active>; rel="next"')
        self.client.opener.open.side_effect = [first_page, response([{"id": 2, "name": "B"}])]
        self.assertEqual([c["id"] for c in self.client.courses()], [1, 2])
        first, second = [call.args[0] for call in self.client.opener.open.call_args_list]
        self.assertEqual(first.full_url, "https://canvas.example.edu/api/v1/courses?enrollment_state=active&per_page=100")
        self.assertEqual(second.full_url, "https://canvas.example.edu/api/v1/courses?page=2&enrollment_state=active")
        self.assertEqual(second.get_header("Authorization"), "Bearer fixture-token")

    def test_announcements_query_and_pagination(self):
        first_page = response([{"id": 5}], '</api/v1/announcements?page=2>; rel="next"')
        self.client.opener.open.side_effect = [first_page, response([{"id": 6}])]
        start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        end = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
        self.assertEqual([a["id"] for a in self.client.announcements(9, start, end)], [5, 6])
        first, second = [call.args[0].full_url for call in self.client.opener.open.call_args_list]
        self.assertEqual(
            first,
            "https://canvas.example.edu/api/v1/announcements?context_codes[]=course_9"
            "&start_date=2026-09-25T12:00:00Z&end_date=2026-11-24T12:00:00Z&per_page=100",
        )
        self.assertEqual(second, "https://canvas.example.edu/api/v1/announcements?page=2")

    def test_new_endpoints_refuse_cross_origin_and_non_api_pagination(self):
        start = datetime(2026, 9, 25, tzinfo=timezone.utc)
        cases = [
            ('<https://evil.example/api/v1/courses?page=2>; rel="next"', lambda: self.client.courses()),
            ('<http://canvas.example.edu/api/v1/courses?page=2>; rel="next"', lambda: self.client.courses()),
            ('</login?page=2>; rel="next"', lambda: self.client.announcements(9, start, start)),
            ('<https://canvas.example.edu:8443/api/v1/x>; rel="next"', lambda: self.client.assignments(9, True)),
        ]
        for link, call in cases:
            with self.subTest(link=link):
                self.client.opener = Mock()
                self.client.opener.open.return_value = response([{"id": 1}], link)
                with self.assertRaisesRegex(ValueError, "Invalid Canvas pagination URL"):
                    list(call())
                self.client.opener.open.assert_called_once()

    def test_repeated_next_link_is_rejected(self):
        self.client.opener.open.side_effect = [
            response([], '</api/v1/courses?page=2>; rel="next"'),
            response([], '</api/v1/courses?page=2>; rel="next"'),
        ]
        with self.assertRaisesRegex(ValueError, "Invalid Canvas pagination URL"):
            list(self.client.courses())

    def test_rejects_non_list_course_and_announcement_responses(self):
        start = datetime(2026, 9, 25, tzinfo=timezone.utc)
        self.client.opener.open.return_value = response({"errors": []})
        with self.assertRaisesRegex(ValueError, "unexpected courses response"):
            list(self.client.courses())
        self.client.opener.open.return_value = response([1, 2])
        with self.assertRaisesRegex(ValueError, "unexpected announcements response"):
            list(self.client.announcements(9, start, start))

    def test_rejects_invalid_course_ids_before_any_request(self):
        start = datetime(2026, 9, 25, tzinfo=timezone.utc)
        for bad in (0, -1, True):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    self.client.assignments(bad)
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    self.client.announcements(bad, start, start)
        self.client.opener.open.assert_not_called()

    def test_rejects_non_https_or_non_origin_base_urls(self):
        for base in ("http://canvas.example.edu", "https://user@canvas.example.edu", "https://canvas.example.edu/x", ""):
            with self.subTest(base=base):
                with self.assertRaisesRegex(ValueError, "HTTPS origin"):
                    CanvasClient(base, "token")
        with self.assertRaisesRegex(ValueError, "TOKEN"):
            CanvasClient("https://canvas.example.edu", "  ")
