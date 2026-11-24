"""Offline Canvas client backed by the JSON fixtures shipped in ``fixtures/canvas_demo``.

The fixtures use Canvas response shapes plus a few demo-only keys:

* ``due_offset_hours``, ``posted_offset_hours`` and ``submitted_offset_hours``
  become ``due_at``, ``posted_at`` and ``submission.submitted_at``, measured
  from the start (Monday 00:00 UTC) of the week containing ``now``. Anchoring
  to the week keeps dates stable across syncs, so repeated demo syncs are
  idempotent, while the UI always has upcoming and recently overdue work. When
  a new week starts the dates move forward by seven days, which the sync
  reports as due date changes.
* ``_demo_from_sync``: the record appears only from that sync number on.
* ``_demo_second_sync``: keys merged into the record from the second sync on.

Together the last two let a second demo sync show a new announcement, a new
assignment and a due date change.
"""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "canvas_demo"
DEMO_BASE_URL = "https://canvas.example.com"
_OFFSETS = {"due_offset_hours": "due_at", "posted_offset_hours": "posted_at"}


def load_fixture(name: str):
    with (FIXTURE_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def week_anchor(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _stamp(anchor: datetime, hours: float) -> str:
    return (anchor + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


class DemoCanvasClient:
    """Implements the subset of ``CanvasClient`` that the sync uses, without network access."""

    base_url = DEMO_BASE_URL

    def __init__(self, now: datetime | None = None, sync_number: int = 1):
        self.anchor = week_anchor(now or datetime.now(timezone.utc))
        self.sync_number = sync_number
        self._courses = load_fixture("courses.json")
        self._assignments = load_fixture("assignments.json")
        self._announcements = load_fixture("announcements.json")

    def _materialize(self, records: list[dict]) -> list[dict]:
        result = []
        for source in records:
            record = copy.deepcopy(source)
            if record.pop("_demo_from_sync", 1) > self.sync_number:
                continue
            overrides = record.pop("_demo_second_sync", None)
            if overrides and self.sync_number >= 2:
                record.update(overrides)
            for offset_key, field in _OFFSETS.items():
                if offset_key in record:
                    record[field] = _stamp(self.anchor, record.pop(offset_key))
            if "submitted_offset_hours" in record:
                record.setdefault("submission", {})["submitted_at"] = _stamp(
                    self.anchor, record.pop("submitted_offset_hours")
                )
            result.append(record)
        return result

    def courses(self):
        return iter(copy.deepcopy(self._courses))

    def assignments(self, course_id: int, include_submission: bool = False):
        records = self._materialize(self._assignments.get(str(course_id), []))
        if not include_submission:
            for record in records:
                record.pop("submission", None)
        return iter(records)

    def announcements(self, course_id: int, start_date: datetime, end_date: datetime):
        records = self._materialize(self._announcements.get(str(course_id), []))
        return iter(
            record
            for record in records
            if start_date <= datetime.fromisoformat(record["posted_at"].replace("Z", "+00:00")) <= end_date
        )
