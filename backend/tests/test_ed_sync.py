import copy
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError

from academic_assistant import ed_sync
from academic_assistant.database import LATEST_VERSION, MIGRATIONS, connect, migrate, schema_version
from academic_assistant.ed_sync import EdCourseListError, is_kept, normalize_course_code, sync
from academic_assistant.integrations.ed_demo import DemoEdClient

from test_canvas_sync import NOW, DatabaseTestCase, stamp


def summary(thread_id, kind="announcement", age=timedelta(days=1), pinned=False, text="Body", updated=None,
            now=NOW, **extra):
    created = stamp(now - age)
    return {
        "id": thread_id, "number": thread_id, "title": f"Thread {thread_id}", "type": kind, "category": "General",
        "created_at": created, "is_pinned": pinned, "is_answered": False,
        "url": f"https://edstem.org/us/courses/1/discussion/{thread_id}",
        "updated_at": updated or created, "text": text, **extra,
    }


class FakeEdClient:
    """In-memory stand-in for ``EdClient``; tests mutate ``threads_data`` and ``fail``."""

    def __init__(self):
        self.courses_data = [
            {"id": 1, "code": "CS 106B", "name": "Programming Abstractions"},
            {"id": 2, "code": "CS 103", "name": "Math Foundations"},
        ]
        self.threads_data = {
            1: [
                summary(11, age=timedelta(days=2)),                          # recent announcement
                summary(12, age=timedelta(days=20)),                         # older announcement, kept
                summary(13, age=timedelta(days=40)),                         # too old: filtered
                summary(14, kind="post", age=timedelta(days=90), pinned=True),  # pinned, any age
                summary(15, kind="question", age=timedelta(hours=3)),       # student question: filtered
            ],
            2: [summary(21, age=timedelta(days=1))],
        }
        self.details = {}
        self.detail_calls = []
        self.thread_calls = []
        self.fail = {}

    def courses(self):
        if "courses" in self.fail:
            raise self.fail["courses"]
        return copy.deepcopy(self.courses_data)

    def course_url(self, course_id):
        return f"https://edstem.org/us/courses/{course_id}/discussion"

    def threads(self, course_id, limit=20, with_body=False):
        assert with_body is True and limit == ed_sync.THREAD_LIMIT
        self.thread_calls.append(course_id)
        if course_id in self.fail:
            raise self.fail[course_id]
        return copy.deepcopy(self.threads_data.get(course_id, []))

    def thread(self, thread_id):
        self.detail_calls.append(thread_id)
        if ("thread", thread_id) in self.fail:
            raise self.fail[("thread", thread_id)]
        return {"id": thread_id, "text": self.details.get(thread_id, f"Detail {thread_id}")}


class EdSyncTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeEdClient()

    def thread_ids(self, course_id=None):
        where, params = ("WHERE ed_course_id = ?", (course_id,)) if course_id else ("", ())
        return [row[0] for row in self.db.execute(f"SELECT id FROM ed_threads {where} ORDER BY id", params)]

    def ed_notifications(self):
        return [tuple(row) for row in self.db.execute(
            "SELECT ed_thread_id, type, message, item_id, due_at FROM canvas_notifications"
            " WHERE ed_thread_id IS NOT NULL ORDER BY id"
        )]


class MatchingTests(unittest.TestCase):
    def test_normalizes_to_leading_subject_and_number(self):
        for value in ("CS 106B", "CS106B", "CS-106B Fall 2026", "cs 106b: Programming Abstractions", " CS.106B "):
            with self.subTest(value=value):
                self.assertEqual(normalize_course_code(value), "CS106B")
        self.assertEqual(normalize_course_code("MS&E 211"), "MSE211")
        self.assertEqual(normalize_course_code("HIST 210"), "HIST210")
        self.assertNotEqual(normalize_course_code("CS 106A"), normalize_course_code("CS 106B"))
        for value in (None, "", "Programming Abstractions", "106B", 7):
            with self.subTest(value=value):
                self.assertIsNone(normalize_course_code(value))


class FilterTests(unittest.TestCase):
    def test_keeps_recent_announcements_and_pinned_threads_only(self):
        cases = [
            (summary(1, age=timedelta(days=29)), True),
            (summary(2, age=timedelta(days=31)), False),
            (summary(3, kind="post", age=timedelta(days=400), pinned=True), True),
            (summary(4, kind="announcement", age=timedelta(days=400), pinned=True), True),
            (summary(5, kind="question", age=timedelta(minutes=5)), False),
            (summary(6, kind="post", age=timedelta(minutes=5)), False),
            (dict(summary(7), created_at=None), False),
        ]
        for thread, kept in cases:
            with self.subTest(thread=thread["id"]):
                self.assertEqual(is_kept(thread, NOW), kept)


class EdSyncTests(EdSyncTestCase):
    def test_first_sync_is_baseline_with_recent_announcements_only(self):
        result = sync(self.db, self.fake, NOW)
        self.assertEqual(result, {"courses": 2, "threads_added": 4, "threads_updated": 0,
                                  "notifications_created": 2, "errors": []})
        self.assertEqual(self.thread_ids(), [11, 12, 14, 21])
        self.assertEqual(self.ed_notifications(), [
            (11, "ed_announcement", "New Ed announcement in CS 106B: Thread 11", None, None),
            (21, "ed_announcement", "New Ed announcement in CS 103: Thread 21", None, None),
        ])
        row = self.db.execute("SELECT * FROM ed_threads WHERE id = 14").fetchone()
        self.assertEqual((row["is_pinned"], row["type"], row["text"], row["first_seen_at"]), (1, "post", "Body", stamp(NOW)))
        courses = [tuple(r) for r in self.db.execute("SELECT id, code, url, synced_at FROM ed_courses ORDER BY id")]
        self.assertEqual(courses, [(1, "CS 106B", "https://edstem.org/us/courses/1/discussion", stamp(NOW)),
                                   (2, "CS 103", "https://edstem.org/us/courses/2/discussion", stamp(NOW))])
        self.assertEqual(self.db.execute("SELECT value FROM canvas_state WHERE key = 'ed_last_synced_at'").fetchone()[0],
                         stamp(NOW))

    def test_second_sync_with_same_data_adds_nothing(self):
        sync(self.db, self.fake, NOW)
        again = sync(self.db, self.fake, NOW + timedelta(hours=1))
        self.assertEqual((again["threads_added"], again["threads_updated"], again["notifications_created"]), (0, 0, 0))
        self.assertEqual(self.count("ed_threads"), 4)
        self.assertEqual(self.count("canvas_notifications"), 2)
        self.assertEqual(self.fake.detail_calls, [])  # the list carried the text

    def test_later_syncs_notify_each_new_announcement_but_not_pinned_posts(self):
        sync(self.db, self.fake, NOW)
        self.fake.threads_data[1] += [
            summary(16, age=timedelta(days=12)),  # new to us, older than the baseline window: still notifies
            summary(17, kind="post", age=timedelta(hours=1), pinned=True),
            summary(18, kind="announcement", age=timedelta(hours=1), pinned=True),
        ]
        result = sync(self.db, self.fake, NOW)
        self.assertEqual((result["threads_added"], result["notifications_created"]), (3, 2))
        self.assertEqual([n[0] for n in self.ed_notifications()], [11, 21, 16, 18])

    def test_changes_update_rows_without_notifying(self):
        sync(self.db, self.fake, NOW)
        changed = self.fake.threads_data[1][0]
        changed.update(title="Edited", text="New body", updated_at=stamp(NOW))
        self.fake.threads_data[1][3]["is_pinned"] = False  # unpinned old post: updated, then hidden by the API window
        result = sync(self.db, self.fake, NOW)
        self.assertEqual((result["threads_added"], result["threads_updated"], result["notifications_created"]), (0, 2, 0))
        row = self.db.execute("SELECT title, text FROM ed_threads WHERE id = 11").fetchone()
        self.assertEqual(tuple(row), ("Edited", "New body"))
        self.assertEqual(self.db.execute("SELECT is_pinned FROM ed_threads WHERE id = 14").fetchone()[0], 0)

    def test_detail_requests_only_when_list_has_no_text_and_are_bounded(self):
        self.fake.threads_data = {1: [summary(100 + i, text=None) for i in range(15)], 2: []}
        sync(self.db, self.fake, NOW)
        self.assertEqual(self.fake.detail_calls, list(range(100, 110)))
        texts = dict(self.db.execute("SELECT id, text FROM ed_threads").fetchall())
        self.assertEqual(len(texts), 15)
        self.assertEqual([texts[i] for i in range(100, 110)], [f"Detail {i}" for i in range(100, 110)])
        self.assertEqual([texts[i] for i in range(110, 115)], [None] * 5)

        # The next sync fetches only the threads still without text.
        self.fake.detail_calls.clear()
        result = sync(self.db, self.fake, NOW)
        self.assertEqual(self.fake.detail_calls, list(range(110, 115)))
        self.assertEqual((result["threads_added"], result["threads_updated"]), (0, 5))
        self.fake.detail_calls.clear()
        sync(self.db, self.fake, NOW)
        self.assertEqual(self.fake.detail_calls, [])

    def test_changed_updated_at_refetches_detail(self):
        self.fake.threads_data = {1: [summary(31, text=None), summary(32, text=None)], 2: []}
        sync(self.db, self.fake, NOW)
        self.fake.detail_calls.clear()
        self.fake.threads_data[1][0]["updated_at"] = stamp(NOW)
        self.fake.details[31] = "Edited detail"
        sync(self.db, self.fake, NOW)
        self.assertEqual(self.fake.detail_calls, [31])
        self.assertEqual(self.db.execute("SELECT text FROM ed_threads WHERE id = 31").fetchone()[0], "Edited detail")

    def test_changed_thread_over_budget_keeps_old_updated_at_for_retry(self):
        self.fake.threads_data = {1: [summary(200 + i, text=None) for i in range(10)] + [summary(299, text=None)], 2: []}
        sync(self.db, self.fake, NOW)
        sync(self.db, self.fake, NOW)  # fetches 299's text
        for thread in self.fake.threads_data[1]:
            thread["updated_at"] = stamp(NOW)
        self.fake.detail_calls.clear()
        sync(self.db, self.fake, NOW)
        self.assertEqual(len(self.fake.detail_calls), 10)
        row = self.db.execute("SELECT text, updated_at FROM ed_threads WHERE id = 299").fetchone()
        self.assertEqual(row["text"], "Detail 299")
        self.assertNotEqual(row["updated_at"], stamp(NOW))
        self.fake.detail_calls.clear()
        sync(self.db, self.fake, NOW)
        self.assertEqual(self.fake.detail_calls, [299])

    def test_filtered_threads_never_trigger_detail_requests(self):
        self.fake.threads_data = {1: [summary(41, kind="question", text=None), summary(42, age=timedelta(days=45), text=None)], 2: []}
        result = sync(self.db, self.fake, NOW)
        self.assertEqual((result["threads_added"], self.fake.detail_calls), (0, []))

    def test_per_course_failure_is_isolated_with_fixed_messages(self):
        self.fake.fail[1] = HTTPError("https://us.edstem.org/api?token=secret", 403, "secret", {}, None)
        result = sync(self.db, self.fake, NOW)
        self.assertEqual(result["errors"], [{"course_id": 1, "course_name": "CS 106B", "message": "Ed request failed (HTTP 403)."}])
        self.assertEqual(self.thread_ids(), [21])
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT id, synced_at IS NULL FROM ed_courses ORDER BY id")],
                         [(1, 1), (2, 0)])
        for error, message in [
            (TimeoutError("secret"), "Could not reach Ed."),
            (ValueError("secret"), "Ed returned an unexpected response."),
            (RecursionError("secret"), "Ed returned an unexpected response."),
        ]:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(ed_sync.describe_error(error), message)

    def test_detail_failure_fails_only_that_course_and_writes_nothing_for_it(self):
        self.fake.threads_data[1][0]["text"] = None
        self.fake.fail[("thread", 11)] = ConnectionResetError("secret")
        result = sync(self.db, self.fake, NOW)
        self.assertEqual(result["errors"], [{"course_id": 1, "course_name": "CS 106B", "message": "Could not reach Ed."}])
        self.assertEqual(self.thread_ids(), [21])

    def test_every_course_failing_leaves_last_synced_at_unset(self):
        self.fake.fail[1] = self.fake.fail[2] = OSError("secret")
        self.assertEqual(len(sync(self.db, self.fake, NOW)["errors"]), 2)
        self.assertIsNone(self.db.execute("SELECT value FROM canvas_state WHERE key = 'ed_last_synced_at'").fetchone())

    def test_course_list_failure_raises_safe_error(self):
        self.fake.fail["courses"] = HTTPError("https://us.edstem.org/api/user", 401, "secret", {}, None)
        with self.assertRaises(EdCourseListError) as raised:
            sync(self.db, self.fake, NOW)
        self.assertEqual(str(raised.exception), "Could not fetch the Ed course list. Ed request failed (HTTP 401).")
        self.assertEqual(self.count("ed_courses"), 0)

    def test_notification_must_reference_exactly_one_source(self):
        sync(self.db, self.fake, NOW)
        for item_id, thread_id in ((None, None), (1, 11)):
            with self.subTest(item_id=item_id, thread_id=thread_id), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    "INSERT INTO canvas_notifications (item_id, ed_thread_id, type, message, created_at)"
                    " VALUES (?, ?, 'ed_announcement', 'm', 'x')",
                    (item_id, thread_id),
                )


class EdDemoTests(EdSyncTestCase):
    def test_demo_fixtures_filter_detail_and_second_sync(self):
        first = sync(self.db, DemoEdClient(now=NOW, sync_number=1), NOW)
        self.assertEqual((first["courses"], first["errors"]), (2, []))
        self.assertEqual(self.thread_ids(50106), [880001, 880090, 880101])
        self.assertEqual(self.thread_ids(50103), [990010, 990201])
        faq = self.db.execute("SELECT text, url FROM ed_threads WHERE id = 990010").fetchone()
        self.assertIn("cite the lecture", faq["text"])  # body from the detail response
        self.assertEqual(faq["url"], "https://ed.example.com/us/courses/50103/discussion/990010")
        self.assertEqual([n[0] for n in self.ed_notifications()], [880101, 990201])
        second = sync(self.db, DemoEdClient(now=NOW, sync_number=2), NOW)
        self.assertEqual((second["threads_added"], second["notifications_created"]), (1, 1))
        third = sync(self.db, DemoEdClient(now=NOW, sync_number=3), NOW)
        self.assertEqual((third["threads_added"], third["threads_updated"], third["notifications_created"]), (0, 0, 0))


class MigrationV5Tests(unittest.TestCase):
    def test_upgrades_version_4_database_keeping_notification_rows_and_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
                    " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
                for version, statements in MIGRATIONS[:4]:
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
                connection.execute("INSERT INTO canvas_courses (id, name) VALUES (1, 'C')")
                connection.execute(
                    "INSERT INTO canvas_items (kind, source_id, course_id, title, first_seen_at, updated_at)"
                    " VALUES ('assignment', 7, 1, 't', 'x', 'x')"
                )
                connection.executemany(
                    "INSERT INTO canvas_notifications (id, item_id, type, message, created_at, read_at, due_at)"
                    " VALUES (?, 1, ?, ?, 'x', ?, ?)",
                    [(3, "new_assignment", "a", None, "2026-12-01T00:00:00Z"),
                     (8, "due_date_changed", "b", "2026-11-01T00:00:00Z", None)],
                )
            migrate(path)
            migrate(path)
            self.assertEqual((schema_version(path), LATEST_VERSION), (5, 5))
            with closing(connect(path)) as connection:
                rows = [tuple(r) for r in connection.execute(
                    "SELECT id, item_id, ed_thread_id, type, message, read_at, due_at FROM canvas_notifications ORDER BY id"
                )]
                self.assertEqual(rows, [
                    (3, 1, None, "new_assignment", "a", None, "2026-12-01T00:00:00Z"),
                    (8, 1, None, "due_date_changed", "b", "2026-11-01T00:00:00Z", None),
                ])
                indexes = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
                self.assertLessEqual({"canvas_notifications_unread", "canvas_notifications_ed_thread"}, indexes)
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                self.assertLessEqual({"ed_courses", "ed_threads", "canvas_notifications"}, tables)
                self.assertNotIn("canvas_notifications_v5", tables)
                # AUTOINCREMENT continues after the highest preserved id.
                cursor = connection.execute(
                    "INSERT INTO canvas_notifications (item_id, type, message, created_at) VALUES (1, 'new_assignment', 'c', 'x')"
                )
                self.assertEqual(cursor.lastrowid, 9)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                versions = [r[0] for r in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
            self.assertEqual(versions, [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
