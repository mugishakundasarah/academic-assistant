import copy
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

from academic_assistant.canvas_sync import (
    CourseListError,
    classify,
    describe_error,
    normalize_announcement,
    normalize_time,
    sync,
)
from academic_assistant.database import connect, migrate
from academic_assistant.integrations.canvas_demo import DemoCanvasClient, week_anchor
from academic_assistant.integrations.canvas_html import html_to_text_and_links, safe_url

BASE = "https://canvas.example.edu"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeClient:
    """In-memory client; tests mutate ``courses_data``, ``assignments_data`` and ``announcements_data``."""

    base_url = BASE

    def __init__(self):
        self.courses_data = [
            {"id": 1, "name": "Course One", "course_code": "C1"},
            {"id": 2, "name": "Course Two", "course_code": "C2"},
        ]
        self.assignments_data = {
            1: [
                {
                    "id": 10, "name": "Essay", "description": "<p>Write it</p>",
                    "due_at": stamp(NOW + timedelta(days=3)), "html_url": f"{BASE}/courses/1/assignments/10",
                    "points_possible": 10, "submission_types": ["online_upload"],
                    "submission": {"workflow_state": "unsubmitted", "submitted_at": None, "missing": False},
                },
            ],
            2: [
                {
                    "id": 20, "name": "Reading", "description": "<p>Read <a href='/courses/2/files/3/download'>ch1</a></p>",
                    "due_at": None, "submission_types": ["none"], "submission": {},
                },
            ],
        }
        self.announcements_data = {
            1: [
                {"id": 100, "title": "Recent", "message": "<p>Hi</p>", "posted_at": stamp(NOW - timedelta(days=2)),
                 "author": {"display_name": "Prof"}},
                {"id": 101, "title": "Old", "message": "<p>Old news</p>", "posted_at": stamp(NOW - timedelta(days=20))},
            ],
            2: [],
        }
        self.fail = {}
        self.announcement_calls = []

    def courses(self):
        if "courses" in self.fail:
            raise self.fail["courses"]
        return iter(copy.deepcopy(self.courses_data))

    def assignments(self, course_id, include_submission=False):
        assert include_submission is True
        if course_id in self.fail:
            raise self.fail[course_id]
        return iter(copy.deepcopy(self.assignments_data.get(course_id, [])))

    def announcements(self, course_id, start_date, end_date):
        self.announcement_calls.append((course_id, start_date, end_date))
        return iter(copy.deepcopy(self.announcements_data.get(course_id, [])))


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.sqlite3"
        migrate(self.path)
        self.db = connect(self.path)
        self.addCleanup(self.db.close)

    def count(self, table, where="1", params=()):
        return self.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]

    def notifications(self):
        return [tuple(row) for row in self.db.execute(
            """SELECT n.type, i.kind, i.source_id, n.message FROM canvas_notifications n
               JOIN canvas_items i ON i.id = n.item_id ORDER BY n.id"""
        )]


class HtmlTests(unittest.TestCase):
    def test_converts_blocks_lists_and_entities_to_plain_text(self):
        html = (
            "<h2>Week&nbsp;6</h2><p>Read   the\n chapter &amp; <b>take</b> notes.</p>"
            "<ul><li>First</li><li> Second </li></ul><p>Line one<br>Line two</p>"
            "<script>alert('x')</script><style>p{}</style><div></div>"
        )
        text, links = html_to_text_and_links(html, BASE)
        self.assertEqual(
            text,
            "Week 6\n\nRead the chapter & take notes.\n\n- First\n- Second\n\nLine one\nLine two",
        )
        self.assertNotIn("<", text)
        self.assertEqual(links, [])

    def test_empty_and_non_string_bodies(self):
        self.assertEqual(html_to_text_and_links(None, BASE), ("", []))
        self.assertEqual(html_to_text_and_links("   ", BASE), ("", []))
        self.assertEqual(html_to_text_and_links(5, BASE), ("", []))

    def test_extracts_only_safe_absolute_http_links(self):
        html = """
            <a href="/courses/1/files/9/download?wrap=1">Syllabus (PDF)</a>
            <a href="https://canvas.example.edu/courses/1/files/9/download?wrap=1">duplicate</a>
            <a href="https://example.org/article">Article</a>
            <a href="//cdn.example.org/x.pdf"></a>
            <a href="javascript:alert(1)">js</a>
            <a href=" JavaScript:alert(1)">js2</a>
            <a href="java&#09;script:alert(1)">js3</a>
            <a href="data:text/html;base64,PHNjcmlwdD4=">data</a>
            <a href="mailto:prof@example.edu">mail</a>
            <a href="#section">frag</a>
            <a href="https://user:pw@evil.example/x">creds</a>
            <a href="https://canvas.example.edu:99999/x">bad port</a>
            <a>no href</a>
            <a href="vbscript:msgbox">vb</a>
            <a href="relative/page">relative</a>
        """
        text, links = html_to_text_and_links(html, BASE)
        self.assertEqual(links, [
            {"title": "Syllabus (PDF)", "url": f"{BASE}/courses/1/files/9/download?wrap=1", "kind": "file"},
            {"title": "Article", "url": "https://example.org/article", "kind": "link"},
            {"title": "x.pdf", "url": "https://cdn.example.org/x.pdf", "kind": "link"},
            {"title": "relative", "url": f"{BASE}/relative/page", "kind": "link"},
        ])
        self.assertIn("js", text)  # anchor text stays readable even when the link is dropped

    def test_safe_url(self):
        self.assertEqual(safe_url("/files/1", BASE), f"{BASE}/files/1")
        self.assertEqual(safe_url("http://example.org", BASE), "http://example.org")
        for bad in ("javascript:alert(1)", "\x01javascript:alert(1)", "data:,x", "ftp://x/y", "", None, 3, "#top"):
            with self.subTest(bad=bad):
                self.assertIsNone(safe_url(bad, BASE))


class ClassificationTests(unittest.TestCase):
    def test_actions(self):
        cases = [
            (["none"], "read"),
            (["not_graded"], "read"),
            (["none", "not_graded"], "read"),
            (["online_quiz"], "quiz"),
            (["discussion_topic"], "discussion"),
            (["online_upload"], "submit"),
            (["online_text_entry", "online_url"], "submit"),
            (["on_paper"], "submit"),
            (["external_tool"], "submit"),
        ]
        for types, action in cases:
            with self.subTest(types=types):
                self.assertEqual(classify(types, None)[0], action)

    def test_completion_and_missing(self):
        self.assertEqual(classify(["online_upload"], {"workflow_state": "unsubmitted"})[1:], (False, False))
        for state in ("submitted", "graded", "pending_review"):
            self.assertTrue(classify(["online_upload"], {"workflow_state": state})[1])
        self.assertTrue(classify(["online_upload"], {"workflow_state": "unsubmitted", "submitted_at": "2026-11-01T00:00:00Z"})[1])
        self.assertEqual(classify(["online_upload"], {"missing": True})[1:], (False, True))
        self.assertEqual(classify(["online_upload"], "junk")[1:], (False, False))

    def test_announcement_attachments_become_file_links(self):
        item = normalize_announcement({
            "id": 5, "title": "T",
            "message": f'<p><a href="{BASE}/files/1/download">Slides</a></p>',
            "posted_at": "2026-11-20T10:00:00-05:00",
            "attachments": [
                {"display_name": "slides.pdf", "url": f"{BASE}/files/1/download"},
                {"display_name": "notes.docx", "url": f"{BASE}/files/2/download?verifier=abc"},
                {"display_name": "evil", "url": "javascript:alert(1)"},
            ],
        }, BASE)
        self.assertEqual(item["posted_at"], "2026-11-20T15:00:00Z")
        self.assertEqual([(l["title"], l["kind"]) for l in item["links"]], [("Slides", "file"), ("notes.docx", "file")])

    def test_normalize_time(self):
        self.assertEqual(normalize_time("2026-11-20T10:00:00.123Z"), "2026-11-20T10:00:00Z")
        self.assertEqual(normalize_time("2026-11-20T10:00:00"), "2026-11-20T10:00:00Z")
        self.assertIsNone(normalize_time("not a date"))
        self.assertIsNone(normalize_time(None))


class SyncTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = FakeClient()

    def test_first_sync_is_baseline_with_recent_announcements_only(self):
        result = sync(self.db, self.client, NOW)
        self.assertEqual(result["courses"], 2)
        self.assertEqual(result["items_added"], 4)
        self.assertEqual(result["notifications_created"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["started_at"], "2026-11-25T12:00:00Z")
        self.assertEqual(self.notifications(), [("new_announcement", "announcement", 100, "New announcement in C1: Recent")])
        self.assertEqual(self.client.announcement_calls[0][1:], (NOW - timedelta(days=60), NOW))
        self.assertEqual(self.count("canvas_courses", "synced_at = ?", ("2026-11-25T12:00:00Z",)), 2)

    def test_sync_twice_creates_no_duplicates(self):
        sync(self.db, self.client, NOW)
        before = (self.count("canvas_items"), self.count("canvas_notifications"))
        result = sync(self.db, self.client, NOW + timedelta(hours=1))
        self.assertEqual((result["items_added"], result["items_updated"], result["notifications_created"]), (0, 0, 0))
        self.assertEqual((self.count("canvas_items"), self.count("canvas_notifications")), before)

    def test_later_sync_notifies_new_items_and_changes(self):
        sync(self.db, self.client, NOW)
        new_due = NOW + timedelta(days=5, hours=6)
        self.client.assignments_data[1][0]["due_at"] = stamp(new_due)
        self.client.assignments_data[2][0]["name"] = "Reading (revised)"
        self.client.assignments_data[1].append({
            "id": 11, "name": "Problem set", "due_at": stamp(NOW + timedelta(days=9)),
            "submission_types": ["online_upload"],
        })
        self.client.announcements_data[2].append(
            {"id": 200, "title": "Exam info", "message": "<p>Room 1</p>", "posted_at": stamp(NOW - timedelta(days=30))}
        )
        result = sync(self.db, self.client, NOW + timedelta(hours=1))
        self.assertEqual((result["items_added"], result["items_updated"], result["notifications_created"]), (2, 2, 4))
        self.assertEqual(self.notifications()[1:], [
            ("due_date_changed", "assignment", 10, "Due date changed in C1: Essay is now due Nov 30, 2026 18:00 UTC"),
            ("new_assignment", "assignment", 11, "New assignment in C1: Problem set (due Dec 4, 2026 12:00 UTC)"),
            ("assignment_updated", "assignment", 20, "Assignment updated in C2: Reading (revised)"),
            ("new_announcement", "announcement", 200, "New announcement in C2: Exam info"),
        ])
        row = self.db.execute("SELECT due_at, first_seen_at, updated_at FROM canvas_items WHERE source_id = 10").fetchone()
        self.assertEqual(tuple(row), (stamp(new_due), "2026-11-25T12:00:00Z", "2026-11-25T13:00:00Z"))
        # And the changed data is stable on a third run.
        again = sync(self.db, self.client, NOW + timedelta(hours=2))
        self.assertEqual((again["items_added"], again["items_updated"], again["notifications_created"]), (0, 0, 0))

    def test_submission_change_updates_without_notifying(self):
        sync(self.db, self.client, NOW)
        self.client.assignments_data[1][0]["submission"] = {"workflow_state": "submitted"}
        result = sync(self.db, self.client, NOW)
        self.assertEqual((result["items_updated"], result["notifications_created"]), (1, 0))
        self.assertEqual(self.db.execute("SELECT completed FROM canvas_items WHERE source_id = 10").fetchone()[0], 1)

    def test_due_date_removed_message(self):
        sync(self.db, self.client, NOW)
        self.client.assignments_data[1][0]["due_at"] = None
        sync(self.db, self.client, NOW)
        self.assertEqual(self.notifications()[-1][0], "due_date_changed")
        self.assertIn("no longer has a due date", self.notifications()[-1][3])

    def test_per_course_failure_is_isolated_and_safe(self):
        self.client.fail[1] = HTTPError(f"{BASE}/api/v1/courses/1?access_token=secret-token", 403, "Forbidden", {}, None)
        result = sync(self.db, self.client, NOW)
        self.assertEqual(result["errors"], [{"course_id": 1, "course_name": "Course One", "message": "Canvas request failed (HTTP 403)."}])
        self.assertNotIn("secret", str(result))
        self.assertEqual(self.count("canvas_items", "course_id = 2"), 1)
        self.assertEqual(self.count("canvas_items", "course_id = 1"), 0)
        self.assertIsNone(self.db.execute("SELECT synced_at FROM canvas_courses WHERE id = 1").fetchone()[0])
        # The failed course's first successful sync is still treated as its baseline.
        del self.client.fail[1]
        result = sync(self.db, self.client, NOW)
        self.assertEqual(result["errors"], [])
        self.assertEqual([n[0] for n in self.notifications()], ["new_announcement"])

    def test_error_messages_never_include_exception_text(self):
        for error, message in [
            (URLError("token=secret"), "Could not reach Canvas."),
            (TimeoutError("secret"), "Could not reach Canvas."),
            (ValueError("secret"), "Canvas returned an unexpected response."),
            (ConnectionResetError("secret"), "Could not reach Canvas."),
        ]:
            self.assertEqual(describe_error(error), message)

    def test_course_list_failure_raises_safe_error_and_writes_nothing(self):
        self.client.fail["courses"] = URLError("secret-token")
        with self.assertRaises(CourseListError) as caught:
            sync(self.db, self.client, NOW)
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(self.count("canvas_courses"), 0)
        self.assertEqual(self.count("canvas_state"), 0)

    def test_skips_malformed_records(self):
        self.client.courses_data.append({"id": 3, "access_restricted_by_date": True})
        self.client.courses_data.append({"name": "No id"})
        self.client.assignments_data[1].append({"name": "No id"})
        result = sync(self.db, self.client, NOW)
        self.assertEqual(result["courses"], 2)
        self.assertEqual(self.count("canvas_items", "kind = 'assignment'"), 2)

    def test_database_errors_roll_back_the_course(self):
        self.db.execute("DROP TABLE canvas_notifications")
        with self.assertRaises(sqlite3.Error):
            sync(self.db, self.client, NOW)
        self.assertEqual(self.count("canvas_items"), 0)


class DemoClientTests(DatabaseTestCase):
    def test_demo_fixtures_cover_the_ui_cases(self):
        client = DemoCanvasClient(NOW, sync_number=1)
        result = sync(self.db, client, NOW)
        self.assertEqual(result["courses"], 3)
        self.assertEqual(result["errors"], [])
        now = stamp(NOW)
        self.assertGreater(self.count("canvas_items", "kind = 'assignment' AND completed = 0 AND due_at >= ?", (now,)), 3)
        self.assertGreater(self.count(
            "canvas_items", "kind = 'assignment' AND completed = 0 AND due_at < ? AND due_at >= ?",
            (now, stamp(NOW - timedelta(days=14))),
        ), 0)
        self.assertGreater(self.count("canvas_items", "completed = 1"), 0)
        self.assertGreater(self.count("canvas_items", "missing = 1"), 0)
        actions = {row[0] for row in self.db.execute("SELECT action FROM canvas_items WHERE kind = 'assignment'")}
        self.assertEqual(actions, {"read", "submit", "quiz", "discussion"})
        links = " ".join(row[0] for row in self.db.execute("SELECT links_json FROM canvas_items"))
        self.assertIn('"kind": "file"', links)
        self.assertNotIn("javascript", links)
        self.assertNotIn("data:", links)
        self.assertNotIn("mailto", links)
        self.assertEqual(self.count("canvas_items", "text LIKE '%<%'"), 0)
        self.assertEqual(self.count("canvas_notifications", "type = 'new_announcement'"), 3)

    def test_demo_is_idempotent_and_second_sync_shows_changes(self):
        first = sync(self.db, DemoCanvasClient(NOW, 1), NOW)
        repeat = sync(self.db, DemoCanvasClient(NOW + timedelta(hours=1), 1), NOW + timedelta(hours=1))
        self.assertEqual((repeat["items_added"], repeat["items_updated"], repeat["notifications_created"]), (0, 0, 0))
        second = sync(self.db, DemoCanvasClient(NOW, 2), NOW + timedelta(hours=2))
        self.assertEqual(second["items_added"], 2)
        types = [n[0] for n in self.notifications()[first["notifications_created"]:]]
        self.assertEqual(sorted(types), ["due_date_changed", "new_announcement", "new_assignment"])
        third = sync(self.db, DemoCanvasClient(NOW, 3), NOW + timedelta(hours=3))
        self.assertEqual(third["notifications_created"], 0)

    def test_week_anchor(self):
        self.assertEqual(week_anchor(NOW), datetime(2026, 11, 23, tzinfo=timezone.utc))
        sunday = datetime(2026, 11, 29, 23, 59, tzinfo=timezone.utc)
        self.assertEqual(week_anchor(sunday), datetime(2026, 11, 23, tzinfo=timezone.utc))

    def test_demo_has_upcoming_and_overdue_on_every_day_of_the_week(self):
        for hours in range(0, 7 * 24, 6):
            now = datetime(2026, 11, 23, tzinfo=timezone.utc) + timedelta(hours=hours)
            records = list(DemoCanvasClient(now).assignments(1001, True)) + list(DemoCanvasClient(now).assignments(1002, True))
            due = [r["due_at"] for r in records if r.get("due_at") and r["submission"].get("workflow_state") == "unsubmitted"]
            with self.subTest(now=now):
                self.assertTrue(any(d >= stamp(now) for d in due))
                self.assertTrue(any(stamp(now - timedelta(days=14)) <= d < stamp(now) for d in due))


if __name__ == "__main__":
    unittest.main()
