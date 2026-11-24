import io
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock

from academic_assistant.database import migrate, schema_version
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
            self.assertEqual(schema_version(path), 1)

    def test_schema_check_rejects_missing_migration_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.sqlite3"
            migrate(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("DELETE FROM schema_migrations")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "missing schema version"):
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
