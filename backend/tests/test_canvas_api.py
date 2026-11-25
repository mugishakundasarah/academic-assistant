import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from academic_assistant import main

from test_canvas_sync import BASE, FakeClient, stamp

ITEM_KEYS = {
    "id", "kind", "course_id", "course_name", "title", "text", "html_url", "due_at", "posted_at", "action",
    "completed", "missing", "points_possible", "author", "links", "first_seen_at", "updated_at", "platform",
}
COURSE_KEYS = {"id", "name", "course_code", "synced_at", "open_count", "next_due_at", "unread_count", "ed_course_id"}


class ApiTestCase(unittest.TestCase):
    env: dict = {}

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = {
            "SQLITE_PATH": str(Path(directory.name) / "api.sqlite3"),
            # Empty values keep a developer's backend/.env from leaking into tests.
            "CANVAS_BASE_URL": "",
            "CANVAS_API_TOKEN": "",
            "CANVAS_DEMO": "",
            **self.env,
        }
        env_patch = patch.dict(os.environ, environment)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def assert_item_shape(self, item):
        self.assertEqual(set(item), ITEM_KEYS)
        for key in ("due_at", "posted_at", "first_seen_at", "updated_at"):
            if item[key] is not None:
                self.assertRegex(item[key], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        for link in item["links"]:
            self.assertEqual(set(link), {"title", "url", "kind"})
            self.assertRegex(link["url"], r"^https?://")
            self.assertIn(link["kind"], ("file", "link"))
        self.assertIn(item["platform"], ("canvas", "gradescope"))
        if item["kind"] == "announcement":
            self.assertEqual(item["platform"], "canvas")


class UnconfiguredApiTests(ApiTestCase):
    def test_status_and_sync_without_configuration(self):
        status = self.client.get("/api/canvas/status").json()
        self.assertEqual(status, {"configured": False, "demo": False, "syncing": False, "last_synced_at": None})
        response = self.client.post("/api/canvas/sync")
        self.assertEqual(response.status_code, 503)
        self.assertIn("CANVAS_BASE_URL", response.json()["detail"])

    def test_health_reports_latest_schema(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok", "schema_version": 5})

    def test_empty_lists_and_404s(self):
        self.assertEqual(self.client.get("/api/courses").json(), {"courses": []})
        self.assertEqual(self.client.get("/api/upcoming").json(), {"overdue": [], "upcoming": []})
        self.assertEqual(self.client.get("/api/notifications").json(), {"notifications": [], "unread_count": 0})
        self.assertEqual(self.client.get("/api/courses/5").status_code, 404)
        self.assertEqual(self.client.get("/api/courses/5/items").status_code, 404)
        self.assertEqual(self.client.post("/api/notifications/5/read").status_code, 404)
        self.assertEqual(self.client.post("/api/notifications/read-all").json(), {"updated": 0})

    def test_validation_errors(self):
        for path in ("/api/upcoming?limit=0", "/api/upcoming?limit=51", "/api/notifications?limit=0",
                     "/api/courses/abc", "/api/notifications/x/read"):
            with self.subTest(path=path):
                method = self.client.post if path.endswith("/read") else self.client.get
                self.assertEqual(method(path).status_code, 422)

    def test_oversized_and_non_positive_ids_are_422(self):
        huge = "99999999999999999999"
        for method, path in [
            (self.client.get, f"/api/courses/{huge}"),
            (self.client.get, f"/api/courses/{huge}/items"),
            (self.client.post, f"/api/notifications/{huge}/read"),
            (self.client.get, f"/api/courses/{2**63}"),
            (self.client.get, "/api/courses/0"),
        ]:
            with self.subTest(path=path):
                self.assertEqual(method(path).status_code, 422)
        self.assertEqual(self.client.get(f"/api/courses/{2**63 - 1}").status_code, 404)


class LiveApiTests(ApiTestCase):
    env = {"CANVAS_BASE_URL": BASE, "CANVAS_API_TOKEN": "secret-token"}

    def setUp(self):
        super().setUp()
        self.fake = FakeClient()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        # Shift the fixture so it is relative to the real clock the API uses.
        self.fake.assignments_data[1][0]["due_at"] = stamp(now + timedelta(days=3))
        self.fake.assignments_data[1].append({
            "id": 12, "name": "Late lab", "due_at": stamp(now - timedelta(days=2)),
            "submission_types": ["online_upload"], "submission": {"missing": True},
        })
        self.fake.assignments_data[1].append({
            "id": 13, "name": "Done", "due_at": stamp(now - timedelta(days=1)),
            "submission_types": ["online_upload"], "submission": {"workflow_state": "graded"},
        })
        self.fake.announcements_data[1][0]["posted_at"] = stamp(now - timedelta(days=1))
        factory = patch.object(main, "CanvasClient", side_effect=self.make_client)
        factory.start()
        self.addCleanup(factory.stop)

    def make_client(self, base_url, token):
        self.assertEqual((base_url, token), (BASE, "secret-token"))
        return self.fake

    def test_sync_and_read_endpoints(self):
        status = self.client.get("/api/canvas/status").json()
        self.assertEqual((status["configured"], status["demo"]), (True, False))
        result = self.client.post("/api/canvas/sync")
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(set(body), {"started_at", "finished_at", "courses", "items_added", "items_updated",
                                     "notifications_created", "errors"})
        self.assertEqual((body["courses"], body["items_added"], body["notifications_created"]), (2, 6, 1))
        self.assertEqual(self.client.get("/api/canvas/status").json()["last_synced_at"], body["finished_at"])

        courses = self.client.get("/api/courses").json()["courses"]
        self.assertEqual([c["name"] for c in courses], ["Course One", "Course Two"])
        one = courses[0]
        self.assertEqual(set(one), COURSE_KEYS)
        self.assertEqual((one["open_count"], one["unread_count"]), (1, 1))
        self.assertEqual(one["next_due_at"], self.fake.assignments_data[1][0]["due_at"])
        self.assertEqual(courses[1]["open_count"], 1)  # undated reading counts as open
        self.assertIsNone(courses[1]["next_due_at"])
        self.assertEqual(self.client.get("/api/courses/1").json(), one)

        items = self.client.get("/api/courses/1/items?kind=assignment").json()["items"]
        self.assertEqual([i["title"] for i in items], ["Late lab", "Essay", "Done"])
        for item in items:
            self.assert_item_shape(item)
        self.assertEqual((items[0]["missing"], items[2]["completed"]), (True, True))
        announcements = self.client.get("/api/courses/1/items?kind=announcement").json()["items"]
        self.assertEqual([a["title"] for a in announcements], ["Recent", "Old"])
        self.assertEqual((announcements[0]["author"], announcements[0]["action"]), ("Prof", None))
        both = self.client.get("/api/courses/1/items").json()["items"]
        self.assertEqual(len(both), 5)
        self.assertEqual(self.client.get("/api/courses/1/items?kind=quiz").status_code, 422)

        reading = self.client.get("/api/courses/2/items?kind=assignment").json()["items"][0]
        self.assertEqual(reading["text"], "Read ch1")
        self.assertEqual(reading["links"], [{"title": "ch1", "url": f"{BASE}/courses/2/files/3/download", "kind": "file"}])
        self.assertEqual(reading["action"], "read")

        upcoming = self.client.get("/api/upcoming?limit=1").json()
        self.assertEqual([i["title"] for i in upcoming["upcoming"]], ["Essay"])
        self.assertEqual([i["title"] for i in upcoming["overdue"]], ["Late lab"])

    def test_notifications_read_flow(self):
        self.client.post("/api/canvas/sync")
        self.fake.assignments_data[1][0]["due_at"] = stamp(datetime.now(timezone.utc) + timedelta(days=6))
        self.client.post("/api/canvas/sync")
        listing = self.client.get("/api/notifications").json()
        self.assertEqual(listing["unread_count"], 2)
        self.assertEqual([n["type"] for n in listing["notifications"]], ["due_date_changed", "new_announcement"])
        notification = listing["notifications"][0]
        self.assertEqual(set(notification), {"id", "type", "message", "created_at", "read_at", "due_at", "item", "ed_thread", "ed_course"})
        self.assertEqual(notification["due_at"], notification["item"]["due_at"])
        self.assertRegex(notification["due_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsNone(listing["notifications"][1]["due_at"])  # announcement
        self.assert_item_shape(notification["item"])
        self.assertEqual(notification["item"]["title"], "Essay")

        read = self.client.post(f"/api/notifications/{notification['id']}/read")
        self.assertEqual(read.status_code, 200)
        read_at = read.json()["read_at"]
        self.assertIsNotNone(read_at)
        again = self.client.post(f"/api/notifications/{notification['id']}/read").json()
        self.assertEqual(again["read_at"], read_at)  # idempotent
        unread = self.client.get("/api/notifications?unread_only=true").json()
        self.assertEqual(([n["type"] for n in unread["notifications"]], unread["unread_count"]), (["new_announcement"], 1))
        self.assertEqual(len(self.client.get("/api/notifications?limit=1").json()["notifications"]), 1)
        self.assertEqual(self.client.post("/api/notifications/read-all").json(), {"updated": 1})
        self.assertEqual(self.client.post("/api/notifications/read-all").json(), {"updated": 0})
        self.assertEqual(self.client.get("/api/courses/1").json()["unread_count"], 0)

    def test_course_list_failure_is_502_without_secrets(self):
        self.fake.fail["courses"] = HTTPError(f"{BASE}/api/v1/courses?access_token=secret-token", 401, "secret-token", {}, None)
        response = self.client.post("/api/canvas/sync")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Could not fetch the Canvas course list. Canvas request failed (HTTP 401).")
        self.assertIsNone(self.client.get("/api/canvas/status").json()["last_synced_at"])

    def test_per_course_errors_are_reported(self):
        self.fake.fail[2] = TimeoutError("secret-token")
        body = self.client.post("/api/canvas/sync").json()
        self.assertEqual(body["errors"], [{"course_id": 2, "course_name": "Course Two", "message": "Could not reach Canvas."}])
        self.assertEqual(self.client.get("/api/courses/2").json()["synced_at"], None)

    def test_concurrent_sync_returns_409(self):
        entered, release = threading.Event(), threading.Event()
        original = self.fake.courses

        def slow_courses():
            entered.set()
            release.wait(5)
            return original()

        self.fake.courses = slow_courses
        responses = []
        worker = threading.Thread(target=lambda: responses.append(self.client.post("/api/canvas/sync")))
        worker.start()
        self.assertTrue(entered.wait(5))
        try:
            self.assertTrue(self.client.get("/api/canvas/status").json()["syncing"])
            busy = self.client.post("/api/canvas/sync")
            self.assertEqual(busy.status_code, 409)
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(responses[0].status_code, 200)
        self.assertFalse(self.client.get("/api/canvas/status").json()["syncing"])


class DemoApiTests(ApiTestCase):
    env = {"CANVAS_DEMO": "1"}

    def test_demo_mode_end_to_end(self):
        status = self.client.get("/api/canvas/status").json()
        self.assertEqual((status["configured"], status["demo"]), (False, True))
        first = self.client.post("/api/canvas/sync")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()["courses"], first.json()["errors"]), (3, []))
        repeat = self.client.post("/api/canvas/sync").json()
        self.assertEqual(repeat["notifications_created"], 3)  # second demo sync releases scripted changes
        third = self.client.post("/api/canvas/sync").json()
        self.assertEqual((third["items_added"], third["items_updated"], third["notifications_created"]), (0, 0, 0))

        courses = self.client.get("/api/courses").json()["courses"]
        self.assertEqual([c["course_code"] for c in courses], ["CHEM 31A", "CS 106B", "HIST 210"])
        upcoming = self.client.get("/api/upcoming?limit=50").json()
        self.assertTrue(upcoming["upcoming"])
        self.assertTrue(upcoming["overdue"])
        dues = [i["due_at"] for i in upcoming["upcoming"]]
        self.assertEqual(dues, sorted(dues))
        for item in upcoming["upcoming"] + upcoming["overdue"]:
            self.assert_item_shape(item)
            self.assertFalse(item["completed"])
        notifications = self.client.get("/api/notifications").json()
        self.assertEqual(notifications["unread_count"], 6)
        gradescope = [i for i in upcoming["upcoming"] + upcoming["overdue"] if i["platform"] == "gradescope"]
        self.assertEqual([(i["title"], i["action"]) for i in gradescope],
                         [("Problem Set 3: Recursion tracing (Gradescope)", "submit")])
        for course in courses:
            for item in self.client.get(f"/api/courses/{course['id']}/items").json()["items"]:
                self.assert_item_shape(item)
                self.assertNotIn("<", item["text"])

    def test_demo_does_not_construct_live_client(self):
        with patch.object(main, "CanvasClient", side_effect=AssertionError("live client used")) as live:
            self.assertEqual(self.client.post("/api/canvas/sync").status_code, 200)
        self.assertEqual(live.call_count, 0)



class EnvFileTests(unittest.TestCase):
    def test_env_file_fills_missing_values_without_overriding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("CANVAS_DEMO=1\nCANVAS_BASE_URL=https://from-file.example\n", encoding="utf-8")
            with patch.dict(os.environ, {"CANVAS_BASE_URL": "https://from-env.example"}):
                os.environ.pop("CANVAS_DEMO", None)
                self.assertTrue(main.load_env_file(path))
                self.assertEqual(os.environ["CANVAS_DEMO"], "1")
                self.assertEqual(os.environ["CANVAS_BASE_URL"], "https://from-env.example")
            self.assertFalse(main.load_env_file(Path(directory) / "missing.env"))


if __name__ == "__main__":
    unittest.main()
