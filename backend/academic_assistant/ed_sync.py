"""Sync low-clutter Ed Discussion threads into SQLite and raise notifications.

``sync(connection, client, now)`` is the entry point. ``client`` is the live
``EdClient`` or the demo client: it needs ``courses()``, ``course_url(id)``,
``threads(course_id, limit, with_body=True)`` and ``thread(id)``.

Only staff-style posts are kept, to keep the app uncluttered: threads of type
``announcement`` created in the last ``THREAD_WINDOW`` and pinned threads of
any age. Thread text comes from the list response when it carries a body;
otherwise at most ``MAX_DETAIL_REQUESTS`` detail requests per course and sync
fetch it, for kept threads that are new, changed (Ed ``updated_at``) or still
without text. Threads left over stay without text (or keep their old text and
old ``updated_at``) and are retried by the next sync.

As in the Canvas sync, a course's network reads happen before its writes and
its writes are one transaction, so a failing course leaves no partial rows.
Error messages are fixed strings and never contain exception text.
"""

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from urllib.error import HTTPError

from .canvas_sync import _transaction, iso, parse_time

THREAD_LIMIT = 50
THREAD_WINDOW = timedelta(days=30)
BASELINE_WINDOW = timedelta(days=7)
MAX_DETAIL_REQUESTS = 10

FETCH_ERRORS = (OSError, ValueError, TypeError, RecursionError, HTTPException)

# Columns compared to decide whether a stored thread changed.
_THREAD_FIELDS = (
    "ed_course_id", "title", "type", "category", "created_at", "is_pinned", "is_answered", "text", "url",
    "updated_at",
)


class EdCourseListError(Exception):
    """The Ed course list could not be fetched; ``str()`` is safe to show."""


def describe_error(error: BaseException) -> str:
    """Map an Ed fetch failure to a fixed message without request details."""
    if isinstance(error, HTTPError):
        return f"Ed request failed (HTTP {int(error.code)})."
    if isinstance(error, json.JSONDecodeError):
        return "Ed returned invalid JSON."
    if isinstance(error, (ValueError, TypeError, RecursionError, HTTPException)):
        return "Ed returned an unexpected response."
    if isinstance(error, OSError):
        return "Could not reach Ed."
    return "Unexpected error while reading Ed."


_PUNCTUATION = re.compile(r"[^A-Z0-9\s]")
_COURSE_TOKEN = re.compile(r"\s*([A-Z]+)\s*(\d+[A-Z]*)")


def normalize_course_code(value: object) -> str | None:
    """Leading subject+number token of a course code: "CS-106B Fall 2026" -> "CS106B".

    Uppercase, delete punctuation, then take the leading letters and the
    number (with any letter suffix) that follows, ignoring spaces between
    them. ``None`` when the value does not start with such a token.
    """
    if not isinstance(value, str):
        return None
    match = _COURSE_TOKEN.match(_PUNCTUATION.sub("", value.upper()))
    return match.group(1) + match.group(2) if match else None


def is_kept(thread: dict, now: datetime) -> bool:
    """Announcements from the last 30 days, and pinned threads of any age."""
    if thread["is_pinned"]:
        return True
    created = parse_time(thread["created_at"])
    return thread["type"] == "announcement" and created is not None and created >= now - THREAD_WINDOW


def _fetch_course(client, course_id: int, connection: sqlite3.Connection, now: datetime) -> list[dict]:
    """Read the course's threads (and the bounded details); no writes."""
    stored = {
        row["id"]: row
        for row in connection.execute(
            "SELECT id, text, updated_at FROM ed_threads WHERE ed_course_id = ?", (course_id,)
        )
    }
    threads = []
    seen = set()
    details = 0
    for summary in client.threads(course_id, THREAD_LIMIT, with_body=True):
        if summary["id"] in seen:
            continue
        seen.add(summary["id"])
        existing = stored.get(summary["id"])
        kept = is_kept(summary, now)
        if not kept and existing is None:
            continue
        thread = dict(summary)
        if existing is not None and thread["text"] is None:
            # Keep known text; refetch only for a kept thread that changed or has none.
            thread["text"] = existing["text"]
            stale = existing["text"] is None or existing["updated_at"] != summary["updated_at"]
            if kept and stale:
                if details < MAX_DETAIL_REQUESTS:
                    details += 1
                    thread["text"] = client.thread(summary["id"])["text"]
                else:
                    thread["updated_at"] = existing["updated_at"]  # retry next sync
        elif thread["text"] is None and kept:
            if details < MAX_DETAIL_REQUESTS:
                details += 1
                thread["text"] = client.thread(summary["id"])["text"]
            else:
                thread["updated_at"] = None  # stored without text; retried next sync
        threads.append(thread)
    return threads


def _upsert_course(connection: sqlite3.Connection, course: dict, url: str | None):
    connection.execute(
        """INSERT INTO ed_courses (id, code, name, url) VALUES (?, ?, ?, ?)
           ON CONFLICT (id) DO UPDATE SET code = excluded.code, name = excluded.name, url = excluded.url""",
        (course["id"], course["code"], course["name"], url),
    )


def _store_course(connection, course: dict, threads: list[dict], now: datetime, totals: dict):
    stamp = iso(now)
    course_id = course["id"]
    baseline = connection.execute(
        "SELECT synced_at IS NULL FROM ed_courses WHERE id = ?", (course_id,)
    ).fetchone()[0]
    recent_cutoff = now - BASELINE_WINDOW
    label = course["code"] or course["name"]
    notifications = []
    for thread in threads:
        values = {
            "ed_course_id": course_id,
            "title": thread["title"],
            "type": thread["type"],
            "category": thread["category"],
            "created_at": thread["created_at"],
            "is_pinned": int(thread["is_pinned"]),
            "is_answered": int(thread["is_answered"]),
            "text": thread["text"],
            "url": thread["url"],
            "updated_at": thread["updated_at"],
        }
        existing = connection.execute("SELECT * FROM ed_threads WHERE id = ?", (thread["id"],)).fetchone()
        if existing is None:
            columns = ("id", *_THREAD_FIELDS, "first_seen_at")
            row = {**values, "id": thread["id"], "first_seen_at": stamp}
            connection.execute(
                f"INSERT INTO ed_threads ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [row[column] for column in columns],
            )
            totals["threads_added"] += 1
            if thread["type"] == "announcement":
                created = parse_time(thread["created_at"])
                if not baseline or (created is not None and created >= recent_cutoff):
                    notifications.append((thread["id"], f"New Ed announcement in {label}: {thread['title']}"))
            continue
        changed = [field for field in _THREAD_FIELDS if existing[field] != values[field]]
        if changed:
            connection.execute(
                f"UPDATE ed_threads SET {', '.join(f'{field} = ?' for field in changed)} WHERE id = ?",
                [values[field] for field in changed] + [thread["id"]],
            )
            totals["threads_updated"] += 1
    connection.executemany(
        "INSERT INTO canvas_notifications (ed_thread_id, type, message, created_at) VALUES (?, 'ed_announcement', ?, ?)",
        [(thread_id, message, stamp) for thread_id, message in notifications],
    )
    totals["notifications_created"] += len(notifications)
    connection.execute("UPDATE ed_courses SET synced_at = ? WHERE id = ?", (stamp, course_id))


def sync(connection: sqlite3.Connection, client, now: datetime | None = None) -> dict:
    """Sync every active Ed course; return ``{courses, threads_added, threads_updated, notifications_created, errors}``.

    Raises ``EdCourseListError`` when the course list cannot be read.
    Per-course failures go in ``errors``. ``ed_last_synced_at`` (in
    ``canvas_state``) is updated unless every course failed.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    try:
        courses = client.courses()
    except FETCH_ERRORS as error:
        raise EdCourseListError(f"Could not fetch the Ed course list. {describe_error(error)}") from None

    totals = {"threads_added": 0, "threads_updated": 0, "notifications_created": 0}
    errors = []
    for course in courses:
        _transaction(connection, _upsert_course, course, client.course_url(course["id"]))
        try:
            threads = _fetch_course(client, course["id"], connection, now)
        except FETCH_ERRORS as error:
            errors.append({"course_id": course["id"], "course_name": course["code"] or course["name"],
                           "message": describe_error(error)})
            continue
        _transaction(connection, _store_course, course, threads, now, totals)

    if not courses or len(errors) < len(courses):
        _transaction(
            connection,
            lambda c: c.execute(
                "INSERT INTO canvas_state (key, value) VALUES ('ed_last_synced_at', ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (iso(now),),
            ),
        )
    return {"courses": len(courses), **totals, "errors": errors}
