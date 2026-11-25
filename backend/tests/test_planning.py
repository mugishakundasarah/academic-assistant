from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

from academic_assistant import main, planning
from academic_assistant.database import connect

from test_canvas_api import ApiTestCase
from test_canvas_sync import BASE, NOW, FakeClient, stamp

# NOW is Wednesday 2026-11-25 12:00 UTC; its week starts Monday 2026-11-23.
WEEK = "2026-11-23T00:00:00Z"


def assignment(source_id, name, due, types=("online_upload",), points=None, submission=None):
    return {
        "id": source_id, "name": name, "due_at": stamp(due) if due else None, "points_possible": points,
        "submission_types": list(types), "submission": submission or {},
        "html_url": f"{BASE}/courses/1/assignments/{source_id}",
    }


class DoByRuleTests(unittest.TestCase):
    def plan(self, action, due, points=None, kind="assignment", finished=False, now=NOW):
        return planning.do_by(kind, action, stamp(due) if due else None, points, finished, now)

    def test_lead_times_and_reasons(self):
        due = NOW + timedelta(days=10)
        cases = [
            ("read", None, 1, "Reading: do it 1 day early"),
            ("quiz", 20, 1, "Quiz: prepare 1 day early"),
            ("discussion", 5, 1, "Discussion: post 1 day early"),
            ("submit", None, 2, "Assignment: start 2 days early"),
            ("submit", 49.5, 2, "Assignment (49.5 pts): start 2 days early"),
            ("submit", 50, 4, "Big assignment (50 pts): start 4 days early"),
            ("submit", 100.0, 4, "Big assignment (100 pts): start 4 days early"),
        ]
        for action, points, days, reason in cases:
            with self.subTest(action=action, points=points):
                self.assertEqual(self.plan(action, due, points), (stamp(due - timedelta(days=days)), reason))

    def test_never_earlier_than_now(self):
        self.assertEqual(self.plan("submit", NOW + timedelta(days=3), 100), (stamp(NOW), planning.DUE_SOON_REASON))
        self.assertEqual(self.plan("read", NOW + timedelta(hours=1)), (stamp(NOW), "Due soon: start today"))
        self.assertEqual(self.plan("quiz", NOW - timedelta(hours=1)), (stamp(NOW), planning.PAST_DUE_REASON))
        # Exactly the lead time away is not clamped.
        self.assertEqual(self.plan("read", NOW + timedelta(days=1))[0], stamp(NOW))
        self.assertEqual(self.plan("read", NOW + timedelta(days=1))[1], "Reading: do it 1 day early")

    def test_null_without_due_date_when_finished_and_for_announcements(self):
        self.assertEqual(self.plan("submit", None, 10), (None, None))
        self.assertEqual(self.plan("submit", NOW + timedelta(days=5), 10, finished=True), (None, None))
        self.assertEqual(self.plan(None, NOW + timedelta(days=5), kind="announcement"), (None, None))

    def test_week_start_is_monday_utc(self):
        self.assertEqual(planning.week_start(NOW), datetime(2026, 11, 23, tzinfo=timezone.utc))
        sunday = datetime(2026, 11, 29, 23, 59, tzinfo=timezone.utc)
        self.assertEqual(planning.week_start(sunday), datetime(2026, 11, 23, tzinfo=timezone.utc))


class PlanningApiTestCase(ApiTestCase):
    env = {"CANVAS_BASE_URL": BASE, "CANVAS_API_TOKEN": "secret-token"}

    def setUp(self):
        super().setUp()
        self.now = NOW
        clock = patch.object(main, "utc_now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.fake = FakeClient()
        self.fake.assignments_data[1] = [
            assignment(10, "Essay", NOW + timedelta(days=3), points=10),                    # Sat 12:00
            assignment(11, "Big project", NOW + timedelta(days=6), points=100),             # next Tue
            assignment(12, "Late lab", NOW - timedelta(days=2), points=20, submission={"missing": True}),
            assignment(13, "Graded", NOW - timedelta(days=1), submission={"workflow_state": "graded"}),
            assignment(14, "Quiz", NOW + timedelta(hours=6), types=("online_quiz",), points=5),  # Wed 18:00
            assignment(15, "Reading", NOW + timedelta(hours=20), types=("none",)),          # Thu 08:00
            assignment(16, "Ancient", NOW - timedelta(days=30), points=10),                 # outside 14 days
        ]
        factory = patch.object(main, "CanvasClient", return_value=self.fake)
        factory.start()
        self.addCleanup(factory.stop)
        self.assertEqual(self.client.post("/api/canvas/sync").status_code, 200)
        self.ids = {item["title"]: item["id"] for item in self.items(1)}

    def items(self, course_id):
        return self.client.get(f"/api/courses/{course_id}/items?kind=assignment").json()["items"]

    def item(self, title):
        return next(item for item in self.items(1) if item["title"] == title)

    def today(self, tz=None):
        response = self.client.get("/api/today" + (f"?tz={tz}" if tz else ""))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class DoneApiTests(PlanningApiTestCase):
    def test_mark_done_and_undo_are_idempotent_and_return_the_item(self):
        essay = self.ids["Essay"]
        first = self.client.post(f"/api/items/{essay}/done")
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assert_item_shape(body)
        self.assertEqual((body["done"], body["finished"], body["completed"]), (True, True, False))
        self.assertEqual((body["do_by"], body["do_by_reason"]), (None, None))
        self.now = NOW + timedelta(minutes=5)
        self.assertEqual(self.client.post(f"/api/items/{essay}/done").json(), body)  # first done_at kept
        with closing(connect(main.app.state.database_path)) as connection:
            self.assertEqual([tuple(r) for r in connection.execute("SELECT item_id, done_at FROM canvas_item_done")],
                             [(essay, stamp(NOW))])

        undone = self.client.delete(f"/api/items/{essay}/done")
        self.assertEqual(undone.status_code, 200)
        self.assertEqual((undone.json()["done"], undone.json()["finished"]), (False, False))
        self.assertIsNotNone(undone.json()["do_by"])
        self.assertEqual(self.client.delete(f"/api/items/{essay}/done").json(), undone.json())

    def test_unknown_and_invalid_ids(self):
        for method in (self.client.post, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method("/api/items/999/done").status_code, 404)
                self.assertEqual(method(f"/api/items/{2**63 - 1}/done").status_code, 404)
                for bad in ("0", "-1", str(2**63), "abc"):
                    self.assertEqual(method(f"/api/items/{bad}/done").status_code, 422)

    def test_done_counts_as_finished_everywhere(self):
        course = self.client.get("/api/courses/1").json()
        # Essay, Big project, Quiz, Reading are open (Late lab and Ancient are past due; Graded is completed).
        self.assertEqual((course["open_count"], course["next_due_at"]), (4, stamp(NOW + timedelta(hours=6))))
        self.client.post(f"/api/items/{self.ids['Quiz']}/done")
        self.client.post(f"/api/items/{self.ids['Late lab']}/done")
        course = self.client.get("/api/courses/1").json()
        self.assertEqual((course["open_count"], course["next_due_at"]), (3, stamp(NOW + timedelta(hours=20))))

        upcoming = self.client.get("/api/upcoming?limit=50").json()
        self.assertEqual([i["title"] for i in upcoming["upcoming"]], ["Reading", "Essay", "Big project"])
        self.assertEqual(upcoming["overdue"], [])

        # To do (unfinished, due ascending) then finished (due descending).
        self.assertEqual([i["title"] for i in self.items(1)],
                         ["Ancient", "Reading", "Essay", "Big project", "Quiz", "Graded", "Late lab"])
        quiz = self.item("Quiz")
        self.assertEqual((quiz["completed"], quiz["done"], quiz["finished"]), (False, True, True))

    def test_sync_never_clears_the_done_flag(self):
        essay = self.ids["Essay"]
        self.client.post(f"/api/items/{essay}/done")
        self.fake.assignments_data[1][0]["due_at"] = stamp(NOW + timedelta(days=5))
        self.fake.assignments_data[1][0]["name"] = "Essay (revised)"
        result = self.client.post("/api/canvas/sync").json()
        self.assertEqual(result["items_updated"], 1)
        item = self.item("Essay (revised)")
        self.assertEqual((item["done"], item["finished"], item["completed"]), (True, True, False))
        self.assertEqual(item["due_at"], stamp(NOW + timedelta(days=5)))
        # Canvas completing it later leaves the local flag in place too.
        self.fake.assignments_data[1][0]["submission"] = {"workflow_state": "submitted"}
        self.client.post("/api/canvas/sync")
        item = self.item("Essay (revised)")
        self.assertEqual((item["done"], item["completed"]), (True, True))

    def test_notifications_carry_the_done_state(self):
        self.client.post(f"/api/items/{self.ids['Essay']}/done")
        self.fake.assignments_data[1][0]["due_at"] = stamp(NOW + timedelta(days=4))
        self.client.post("/api/canvas/sync")
        notification = self.client.get("/api/notifications").json()["notifications"][0]
        self.assertEqual(notification["type"], "due_date_changed")
        self.assertEqual((notification["item"]["done"], notification["item"]["finished"]), (True, True))


class PlanApiTests(PlanningApiTestCase):
    def test_items_carry_do_by_dates(self):
        expected = {
            "Essay": (stamp(NOW + timedelta(days=1)), "Assignment (10 pts): start 2 days early"),
            "Big project": (stamp(NOW + timedelta(days=2)), "Big assignment (100 pts): start 4 days early"),
            "Late lab": (stamp(NOW), "Past due: finish today"),
            "Graded": (None, None),
            "Quiz": (stamp(NOW), "Due soon: start today"),
            "Reading": (stamp(NOW), "Due soon: start today"),
        }
        for item in self.items(1):
            if item["title"] in expected:
                with self.subTest(title=item["title"]):
                    self.assertEqual((item["do_by"], item["do_by_reason"]), expected[item["title"]])
        undated = self.items(2)[0]
        self.assertEqual((undated["due_at"], undated["do_by"], undated["do_by_reason"]), (None, None, None))
        announcement = self.client.get("/api/courses/1/items?kind=announcement").json()["items"][0]
        self.assertIsNone(announcement["do_by"])

    def test_weeks(self):
        weeks = self.client.get("/api/weeks").json()["weeks"]
        self.assertEqual([w["start"] for w in weeks], [WEEK, "2026-11-30T00:00:00Z", "2026-12-07T00:00:00Z"])
        # This week: Late lab (Mon), Quiz (Wed), Essay (Sat). The reading and the graded work do not count.
        self.assertEqual(weeks[0], {"start": WEEK, "load": 3, "heavy": True,
                                    "items": [self.ids["Late lab"], self.ids["Quiz"], self.ids["Essay"]]})
        self.assertEqual(weeks[1], {"start": "2026-11-30T00:00:00Z", "load": 1, "heavy": False,
                                    "items": [self.ids["Big project"]]})
        self.assertEqual(weeks[2]["load"], 0)
        self.assertEqual(len(self.client.get("/api/weeks?count=1").json()["weeks"]), 1)
        for bad in ("0", "13", "x"):
            self.assertEqual(self.client.get(f"/api/weeks?count={bad}").status_code, 422)
        self.client.post(f"/api/items/{self.ids['Essay']}/done")
        week = self.client.get("/api/weeks").json()["weeks"][0]
        self.assertEqual((week["load"], week["heavy"]), (2, False))

    def test_today_in_utc(self):
        today = self.today()
        self.assertEqual(set(today), {"generated_at", "do_today", "due_today", "overdue", "changes", "courses",
                                      "heavy_week"})
        self.assertEqual(today["generated_at"], stamp(NOW))
        titles = lambda key: [item["title"] for item in today[key]]  # noqa: E731
        self.assertEqual(titles("due_today"), ["Quiz"])
        self.assertEqual(titles("overdue"), ["Late lab"])          # "Ancient" is older than 14 days
        self.assertEqual(titles("do_today"), ["Reading"])           # Essay's do-by is tomorrow noon
        self.assertEqual(today["heavy_week"], {"start": WEEK, "load": 3})
        for key in ("do_today", "due_today", "overdue"):
            for item in today[key]:
                self.assert_item_shape(item)
        # The baseline sync announced the recent announcement now.
        self.assertEqual([n["type"] for n in today["changes"]], ["new_announcement"])

        courses = {entry["course"]["id"]: entry for entry in today["courses"]}
        self.assertEqual([entry["course"]["name"] for entry in today["courses"]], ["Course One", "Course Two"])
        self.assertEqual(set(courses[1]["course"]), {"id", "name", "course_code", "synced_at", "open_count",
                                                     "next_due_at", "unread_count", "ed_course_id"})
        # do_by ties (now) are broken by due date.
        self.assertEqual([i["title"] for i in courses[1]["next"]], ["Late lab", "Quiz"])
        self.assertEqual([i["title"] for i in courses[2]["next"]], ["Reading"])   # undated, do_by null

    def test_today_follows_the_time_zone(self):
        # Los Angeles: Wed 04:00, today ends Thu 08:00 UTC, so the 08:00 UTC reading is due tomorrow.
        la = self.today("America/Los_Angeles")
        self.assertEqual([i["title"] for i in la["due_today"]], ["Quiz"])
        self.assertEqual([i["title"] for i in la["do_today"]], ["Reading"])
        # Tokyo: Wed 21:00, today ends Wed 15:00 UTC, so the quiz (18:00 UTC) is due tomorrow but planned today.
        tokyo = self.today("Asia/Tokyo")
        self.assertEqual(tokyo["due_today"], [])
        self.assertEqual([i["title"] for i in tokyo["do_today"]], ["Quiz", "Reading"])
        # Kiritimati (UTC+14): Thu 02:00, today ends Thu 10:00 UTC, so the reading is due today.
        self.assertEqual([i["title"] for i in self.today("Pacific/Kiritimati")["due_today"]], ["Quiz", "Reading"])

    def test_today_rejects_unknown_time_zones(self):
        for tz in ("Nope/Zone", "America", "../etc/passwd", "%2Fetc%2Fpasswd", "a b", "x" * 65, ""):
            with self.subTest(tz=tz):
                self.assertEqual(self.client.get(f"/api/today?tz={tz}").status_code, 422)

    def test_today_updates_by_done_state(self):
        for title in ("Quiz", "Late lab", "Reading", "Essay"):
            self.client.post(f"/api/items/{self.ids[title]}/done")
        today = self.today()
        self.assertEqual((today["do_today"], today["due_today"], today["overdue"]), ([], [], []))
        self.assertIsNone(today["heavy_week"])
        courses = {entry["course"]["id"]: entry for entry in today["courses"]}
        self.assertEqual([i["title"] for i in courses[1]["next"]], ["Big project"])

    def test_changes_are_the_last_24_hours_newest_first_capped(self):
        with closing(connect(main.app.state.database_path)) as connection:
            connection.execute("DELETE FROM canvas_notifications")
            item_id = self.ids["Essay"]
            rows = [(item_id, f"m{index}", stamp(NOW - timedelta(hours=index * 2))) for index in range(14)]
            connection.executemany(
                "INSERT INTO canvas_notifications (item_id, type, message, created_at) VALUES (?, 'new_assignment', ?, ?)",
                rows,
            )
        changes = self.today()["changes"]
        # m0..m12 are within 24 hours (m12 exactly 24 hours ago); newest first, at most 10.
        self.assertEqual([n["message"] for n in changes], [f"m{index}" for index in range(10)])


if __name__ == "__main__":
    unittest.main()
