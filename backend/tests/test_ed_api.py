import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError

from academic_assistant import main

from test_canvas_api import ApiTestCase
from test_canvas_sync import BASE, FakeClient
from test_ed_sync import FakeEdClient, summary

ED_THREAD_KEYS = {"id", "ed_course_id", "title", "type", "category", "created_at", "is_pinned", "is_answered",
                  "text", "url", "first_seen_at"}
ED_COURSE_KEYS = {"id", "code", "name", "url", "synced_at", "canvas_course_id"}
NOTIFICATION_KEYS = {"id", "type", "message", "created_at", "read_at", "due_at", "item", "ed_thread", "ed_course"}


def live_fake_ed() -> FakeEdClient:
    """The sync fixture, re-dated relative to the real clock the API uses."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fake = FakeEdClient()
    fake.threads_data = {
        1: [
            summary(11, age=timedelta(days=2), now=now),
            summary(12, age=timedelta(days=20), now=now),
            summary(13, age=timedelta(days=40), now=now),
            summary(14, kind="post", age=timedelta(days=90), pinned=True, now=now),
            summary(15, kind="question", age=timedelta(hours=3), now=now),
        ],
        2: [summary(21, age=timedelta(days=1), now=now)],
    }
    return fake


class EdApiTestCase(ApiTestCase):
    def setUp(self):
        self.env = {"ED_API_TOKEN": "", "ED_REGION": "", **self.env}
        super().setUp()

    def assert_thread_shape(self, thread):
        self.assertEqual(set(thread), ED_THREAD_KEYS)
        self.assertIsInstance(thread["text"], str)
        self.assertIsInstance(thread["is_pinned"], bool)
        self.assertRegex(thread["url"], r"^https://")


class UnconfiguredEdApiTests(EdApiTestCase):
    def test_sync_status_and_empty_lists(self):
        response = self.client.post("/api/sync")
        self.assertEqual(response.status_code, 503)
        self.assertIn("ED_API_TOKEN", response.json()["detail"])
        self.assertEqual(self.client.get("/api/ed/status").json(),
                         {"configured": False, "demo": False, "last_synced_at": None})
        self.assertEqual(self.client.get("/api/ed/courses").json(), {"courses": []})
        self.assertEqual(self.client.get("/api/ed/courses/5").status_code, 404)
        self.assertEqual(self.client.get("/api/courses/5/ed").status_code, 404)

    def test_invalid_ids_are_422(self):
        for path in ("/api/ed/courses/0", f"/api/ed/courses/{2**63}", "/api/ed/courses/abc",
                     "/api/courses/0/ed", f"/api/courses/{2**63}/ed", "/api/courses/x/ed"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 422)
        self.assertEqual(self.client.get(f"/api/ed/courses/{2**63 - 1}").status_code, 404)

    def test_bad_region_is_not_configured(self):
        with patch.dict("os.environ", {"ED_API_TOKEN": "tok", "ED_REGION": "mars"}):
            self.assertFalse(self.client.get("/api/ed/status").json()["configured"])
            self.assertEqual(self.client.post("/api/sync").status_code, 503)


class EdOnlyApiTests(EdApiTestCase):
    env = {"ED_API_TOKEN": "ed-secret", "ED_REGION": "us"}

    def setUp(self):
        super().setUp()
        self.fake = live_fake_ed()
        factory = patch.object(main, "EdClient", side_effect=self.make_client)
        factory.start()
        self.addCleanup(factory.stop)

    def make_client(self, token, region):
        self.assertEqual((token, region), ("ed-secret", "us"))
        return self.fake

    def test_sync_runs_only_ed_and_lists_unmatched_courses(self):
        self.assertTrue(self.client.get("/api/ed/status").json()["configured"])
        response = self.client.post("/api/sync")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body["canvas"])
        self.assertEqual(body["ed"], {"courses": 2, "threads_added": 4, "threads_updated": 0,
                                      "notifications_created": 2, "errors": []})
        self.assertIsNotNone(self.client.get("/api/ed/status").json()["last_synced_at"])
        self.assertEqual(self.client.post("/api/canvas/sync").status_code, 503)  # Canvas still unconfigured

        courses = self.client.get("/api/ed/courses").json()["courses"]
        self.assertEqual([(c["code"], c["canvas_course_id"]) for c in courses], [("CS 103", None), ("CS 106B", None)])
        for course in courses:
            self.assertEqual(set(course), ED_COURSE_KEYS)
        detail = self.client.get("/api/ed/courses/1").json()
        self.assertEqual(detail["ed_course"]["id"], 1)
        self.assertEqual([t["id"] for t in detail["threads"]], [14, 11, 12])  # pinned first, then newest
        for thread in detail["threads"]:
            self.assert_thread_shape(thread)

        notifications = self.client.get("/api/notifications").json()
        self.assertEqual(notifications["unread_count"], 2)
        first = notifications["notifications"][0]
        self.assertEqual(set(first), NOTIFICATION_KEYS)
        self.assertEqual((first["type"], first["item"], first["due_at"]), ("ed_announcement", None, None))
        self.assert_thread_shape(first["ed_thread"])
        self.assertEqual(set(first["ed_course"]), ED_COURSE_KEYS)
        read = self.client.post(f"/api/notifications/{first['id']}/read").json()
        self.assertIsNotNone(read["read_at"])
        self.assertEqual(read["ed_thread"]["id"], first["ed_thread"]["id"])
        self.assertEqual(self.client.post("/api/notifications/read-all").json(), {"updated": 1})

    def test_threads_outside_the_window_are_hidden_at_read_time(self):
        self.client.post("/api/sync")
        main_db = main.connect(main.app.state.database_path)
        self.addCleanup(main_db.close)
        old = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
        main_db.execute("UPDATE ed_threads SET created_at = ? WHERE id = 12", (old,))
        main_db.execute("UPDATE ed_threads SET is_pinned = 0, created_at = ? WHERE id = 14",
                        (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))  # an unpinned post
        self.assertEqual([t["id"] for t in self.client.get("/api/ed/courses/1").json()["threads"]], [11])

    def test_course_list_failure_is_502_when_ed_is_the_only_source(self):
        self.fake.fail["courses"] = HTTPError("https://us.edstem.org/api/user", 401, "ed-secret", {}, None)
        response = self.client.post("/api/sync")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Could not fetch the Ed course list. Ed request failed (HTTP 401).")
        self.assertNotIn("ed-secret", response.text)

    def test_per_course_errors_are_reported(self):
        self.fake.fail[1] = TimeoutError("ed-secret")
        body = self.client.post("/api/sync").json()
        self.assertEqual(body["ed"]["errors"], [{"course_id": 1, "course_name": "CS 106B", "message": "Could not reach Ed."}])
        self.assertEqual(body["ed"]["threads_added"], 1)

    def test_sync_lock_is_shared_with_canvas_sync(self):
        entered, release = threading.Event(), threading.Event()
        original = self.fake.courses

        def slow_courses():
            entered.set()
            release.wait(5)
            return original()

        self.fake.courses = slow_courses
        responses = []
        worker = threading.Thread(target=lambda: responses.append(self.client.post("/api/sync")))
        worker.start()
        self.assertTrue(entered.wait(5))
        try:
            self.assertEqual(self.client.post("/api/sync").status_code, 409)
            self.assertEqual(self.client.post("/api/canvas/sync").status_code, 409)
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(responses[0].status_code, 200)
        with main.sync_lock:
            self.assertEqual(self.client.post("/api/sync").status_code, 409)


class CanvasAndEdApiTests(EdApiTestCase):
    env = {"CANVAS_BASE_URL": BASE, "CANVAS_API_TOKEN": "secret-token", "ED_API_TOKEN": "ed-secret", "ED_REGION": "us"}

    def setUp(self):
        super().setUp()
        self.canvas = FakeClient()
        self.canvas.courses_data[0]["course_code"] = "CS-106B Fall 2026"
        self.ed = live_fake_ed()
        for name, fake in (("CanvasClient", self.canvas), ("EdClient", self.ed)):
            factory = patch.object(main, name, return_value=fake)
            factory.start()
            self.addCleanup(factory.stop)

    def test_matched_course_shows_ed_threads_and_unread_counts(self):
        body = self.client.post("/api/sync").json()
        self.assertEqual(set(body), {"canvas", "ed"})
        self.assertEqual(body["canvas"]["courses"], 2)
        self.assertEqual(body["ed"]["courses"], 2)

        courses = {c["id"]: c for c in self.client.get("/api/courses").json()["courses"]}
        self.assertEqual((courses[1]["ed_course_id"], courses[2]["ed_course_id"]), (1, None))
        canvas_only = self.client.get("/api/notifications").json()["notifications"]
        canvas_unread = sum(1 for n in canvas_only if n["item"] and n["item"]["course_id"] == 1)
        self.assertEqual(courses[1]["unread_count"], canvas_unread + 1)  # plus the CS 106B Ed announcement
        self.assertEqual(self.client.get("/api/courses/1").json(), courses[1])

        ed = self.client.get("/api/courses/1/ed").json()
        self.assertEqual(ed["ed_course"]["canvas_course_id"], 1)
        self.assertEqual([t["id"] for t in ed["threads"]], [14, 11, 12])
        self.assertEqual(self.client.get("/api/courses/2/ed").json(), {"ed_course": None, "threads": []})
        listing = self.client.get("/api/ed/courses").json()["courses"]
        self.assertEqual({c["id"]: c["canvas_course_id"] for c in listing}, {1: 1, 2: None})

        for notification in self.client.get("/api/notifications").json()["notifications"]:
            self.assertEqual(set(notification), NOTIFICATION_KEYS)
            self.assertNotEqual(notification["item"] is None, notification["ed_thread"] is None)
            if notification["ed_thread"]:
                self.assertEqual(notification["ed_course"]["id"], notification["ed_thread"]["ed_course_id"])
            else:
                self.assertIsNone(notification["ed_course"])
                self.assert_item_shape(notification["item"])

        ed_notification = next(n for n in self.client.get("/api/notifications").json()["notifications"]
                               if n["ed_thread"] and n["ed_thread"]["ed_course_id"] == 1)
        self.client.post(f"/api/notifications/{ed_notification['id']}/read")
        self.assertEqual(self.client.get("/api/courses/1").json()["unread_count"], canvas_unread)

    def test_canvas_list_failure_does_not_block_ed(self):
        self.canvas.fail["courses"] = HTTPError(f"{BASE}/api/v1/courses", 401, "secret-token", {}, None)
        response = self.client.post("/api/sync")
        self.assertEqual(response.status_code, 200)
        canvas = response.json()["canvas"]
        self.assertEqual((canvas["courses"], canvas["errors"]), (0, [
            {"course_id": None, "course_name": None,
             "message": "Could not fetch the Canvas course list. Canvas request failed (HTTP 401)."}]))
        self.assertEqual(response.json()["ed"]["threads_added"], 4)
        self.assertNotIn("secret", response.text)

    def test_both_list_failures_are_502(self):
        self.canvas.fail["courses"] = TimeoutError("secret-token")
        self.ed.fail["courses"] = TimeoutError("ed-secret")
        response = self.client.post("/api/sync")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"],
                         "Could not fetch the Canvas course list. Could not reach Canvas. "
                         "Could not fetch the Ed course list. Could not reach Ed.")

    def test_canvas_sync_endpoint_is_unchanged(self):
        body = self.client.post("/api/canvas/sync").json()
        self.assertEqual(set(body), {"started_at", "finished_at", "courses", "items_added", "items_updated",
                                     "notifications_created", "errors"})
        self.assertEqual(self.ed.thread_calls, [])  # /api/canvas/sync never touches Ed


class DemoEdApiTests(EdApiTestCase):
    env = {"CANVAS_DEMO": "1", "ED_API_TOKEN": "ignored-in-demo"}

    def test_demo_end_to_end(self):
        status = self.client.get("/api/ed/status").json()
        self.assertEqual((status["demo"], status["last_synced_at"]), (True, None))
        with patch.object(main, "EdClient", side_effect=AssertionError("live Ed client used")), \
                patch.object(main, "CanvasClient", side_effect=AssertionError("live Canvas client used")):
            first = self.client.post("/api/sync")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual((first.json()["canvas"]["courses"], first.json()["ed"]["courses"]), (3, 2))
            self.assertEqual(first.json()["ed"]["notifications_created"], 2)
            second = self.client.post("/api/sync").json()
            self.assertEqual((second["ed"]["threads_added"], second["ed"]["notifications_created"]), (1, 1))
            third = self.client.post("/api/sync").json()
            self.assertEqual((third["ed"]["threads_added"], third["ed"]["threads_updated"],
                              third["ed"]["notifications_created"]), (0, 0, 0))
            self.assertEqual(third["canvas"]["notifications_created"], 0)

        cs106b = self.client.get("/api/courses/1001").json()
        self.assertEqual(cs106b["ed_course_id"], 50106)
        ed = self.client.get("/api/courses/1001/ed").json()
        self.assertEqual(ed["ed_course"]["code"], "CS106B")
        self.assertEqual([(t["is_pinned"], t["type"]) for t in ed["threads"]][0], (True, "post"))
        titles = [t["title"] for t in ed["threads"]]
        self.assertNotIn("Is the recursion warmup graded?", titles)
        self.assertNotIn("Welcome to CS 106B", titles)
        for thread in ed["threads"]:
            self.assert_thread_shape(thread)
            self.assertTrue(thread["url"].startswith("https://ed.example.com/"))
        others = [c for c in self.client.get("/api/ed/courses").json()["courses"] if c["canvas_course_id"] is None]
        self.assertEqual([c["code"] for c in others], ["CS 103"])
        cs103 = self.client.get(f"/api/ed/courses/{others[0]['id']}").json()
        self.assertEqual([t["title"] for t in cs103["threads"]], ["Problem Set 5 FAQ", "Problem Set 5 checkpoint graded"])
        notifications = self.client.get("/api/notifications").json()
        self.assertEqual(sum(n["type"] == "ed_announcement" for n in notifications["notifications"]), 3)
        self.assertIsNotNone(self.client.get("/api/ed/status").json()["last_synced_at"])
