"""Offline Ed client backed by the JSON fixtures in ``fixtures/ed_demo``.

``DemoEdClient`` subclasses ``EdClient`` and only replaces the HTTP layer, so
demo data goes through the same parsing as live responses. ``user.json`` is a
``GET /api/user`` response; ``threads.json`` maps an Ed course id to thread
list entries with a few demo-only keys:

* ``created_offset_hours`` and ``updated_offset_hours`` become ``created_at``
  and ``updated_at``, measured from the start of the week (as in the Canvas
  demo), so repeated syncs are idempotent. Threads dated after ``now`` are
  left out.
* ``_demo_from_sync``: the thread appears only from that sync number on.
* ``_detail_document``: the body only the detail response carries, for a list
  entry without ``document`` (exercises the detail request path).

Links point to the placeholder host ``ed.example.com``.
"""

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener

from .canvas import RejectRedirects
from .canvas_demo import _stamp, week_anchor
from .ed import EdClient

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "ed_demo"

_THREADS_PATH = re.compile(r"^/api/courses/(\d+)/threads$")
_THREAD_PATH = re.compile(r"^/api/threads/(\d+)$")


def _load(name: str):
    with (FIXTURE_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


class DemoEdClient(EdClient):
    web_origin = "https://ed.example.com"

    def __init__(self, now: datetime | None = None, sync_number: int = 1):
        # No token: the network is never used.
        self.region = "us"
        self.origin = "https://demo.invalid"
        self.token = ""
        self.opener = build_opener(RejectRedirects())
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.anchor = week_anchor(self.now)
        self.sync_number = sync_number
        self._user = _load("user.json")
        self._threads = _load("threads.json")

    def _materialize(self, course_id: int) -> list[dict]:
        result = []
        for source in self._threads.get(str(course_id), []):
            record = copy.deepcopy(source)
            if record.pop("_demo_from_sync", 1) > self.sync_number:
                continue
            record["created_at"] = _stamp(self.anchor, record.pop("created_offset_hours"))
            record["updated_at"] = _stamp(self.anchor, record.pop("updated_offset_hours"))
            if record["created_at"] > self.now.strftime("%Y-%m-%dT%H:%M:%SZ"):
                continue
            record["course_id"] = course_id
            result.append(record)
        result.sort(key=lambda record: (record["created_at"], record["id"]), reverse=True)
        return result

    def _get(self, path: str, what: str) -> dict:
        parts = urlsplit(path)
        if parts.path == "/api/user":
            return copy.deepcopy(self._user)
        match = _THREADS_PATH.match(parts.path)
        if match:
            query = parse_qs(parts.query)
            offset, limit = int(query["offset"][0]), int(query["limit"][0])
            page = self._materialize(int(match.group(1)))[offset:offset + limit]
            for record in page:
                record.pop("_detail_document", None)
            return {"threads": page}
        match = _THREAD_PATH.match(parts.path)
        if match:
            thread_id = int(match.group(1))
            for course_id in self._threads:
                for record in self._materialize(int(course_id)):
                    if record["id"] == thread_id:
                        detail = record.pop("_detail_document", None)
                        if detail is not None:
                            record["document"] = detail
                        return {"thread": {**record, "answers": []}, "users": []}
        raise ValueError(f"Ed returned an unexpected {what} response")
