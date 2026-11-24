"""Sync Canvas courses, assignments, and announcements into SQLite and raise notifications.

``sync(connection, client, now)`` is the only entry point. ``client`` is any
object with ``base_url``, ``courses()``, ``assignments(course_id,
include_submission=True)`` and ``announcements(course_id, start_date,
end_date)``: the live ``CanvasClient`` or the demo fixture client.

Network reads for a course happen before any write for that course, and each
course's writes are one transaction, so a failing course leaves no partial
rows and does not affect other courses.
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError

from .integrations.canvas_html import dedupe_links, html_to_text_and_links, link_kind, safe_url

ANNOUNCEMENT_WINDOW = timedelta(days=60)
BASELINE_ANNOUNCEMENT_WINDOW = timedelta(days=7)
COMPLETED_STATES = frozenset({"submitted", "graded", "pending_review"})
READ_ONLY_TYPES = frozenset({"none", "not_graded"})

# Columns compared to decide whether an existing item changed.
_ITEM_FIELDS = (
    "course_id", "title", "text", "html_url", "due_at", "posted_at", "action",
    "completed", "missing", "points_possible", "author", "links_json",
)


class CourseListError(Exception):
    """The course list could not be fetched; ``str()`` is safe to show."""


def iso(value: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with a ``Z`` suffix."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_time(value: object) -> str | None:
    parsed = parse_time(value)
    return iso(parsed) if parsed else None


def describe_error(error: BaseException) -> str:
    """Map a Canvas fetch failure to a message that never includes request details."""
    if isinstance(error, HTTPError):
        return f"Canvas request failed (HTTP {error.code})."
    if isinstance(error, json.JSONDecodeError):
        return "Canvas returned invalid JSON."
    if isinstance(error, (URLError, TimeoutError, ConnectionError)):
        return "Could not reach Canvas."
    if isinstance(error, (ValueError, TypeError, HTTPException)):
        return "Canvas returned an unexpected response."
    if isinstance(error, OSError):
        return "Could not reach Canvas."
    return "Unexpected error while reading Canvas."


FETCH_ERRORS = (OSError, ValueError, TypeError, HTTPException)


def classify(submission_types: object, submission: object) -> tuple[str, bool, bool]:
    """Return ``(action, completed, missing)`` for a Canvas assignment."""
    types = {t for t in submission_types if isinstance(t, str)} if isinstance(submission_types, list) else set()
    if types <= READ_ONLY_TYPES:
        action = "read"
    elif "online_quiz" in types:
        action = "quiz"
    elif "discussion_topic" in types:
        action = "discussion"
    else:
        action = "submit"
    if not isinstance(submission, dict):
        submission = {}
    completed = submission.get("workflow_state") in COMPLETED_STATES or bool(submission.get("submitted_at"))
    missing = submission.get("missing") is True
    return action, completed, missing


def _canvas_id(record: dict) -> int | None:
    value = record.get("id")
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def normalize_assignment(record: dict, base_url: str) -> dict | None:
    source_id = _canvas_id(record)
    if source_id is None:
        return None
    text, links = html_to_text_and_links(record.get("description"), base_url)
    action, completed, missing = classify(record.get("submission_types"), record.get("submission"))
    return {
        "kind": "assignment",
        "source_id": source_id,
        "title": _string(record.get("name")) or "Untitled assignment",
        "text": text,
        "html_url": safe_url(record.get("html_url"), base_url),
        "due_at": normalize_time(record.get("due_at")),
        "posted_at": None,
        "action": action,
        "completed": int(completed),
        "missing": int(missing),
        "points_possible": _number(record.get("points_possible")),
        "author": None,
        "links": links,
    }


def normalize_announcement(record: dict, base_url: str) -> dict | None:
    source_id = _canvas_id(record)
    if source_id is None:
        return None
    text, links = html_to_text_and_links(record.get("message"), base_url)
    for attachment in record.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        url = safe_url(attachment.get("url"), base_url)
        if url:
            title = _string(attachment.get("display_name")) or _string(attachment.get("filename")) or "Attachment"
            links.append({"title": title, "url": url, "kind": "file"})
    author = record.get("author")
    author_name = _string(author.get("display_name")) if isinstance(author, dict) else None
    return {
        "kind": "announcement",
        "source_id": source_id,
        "title": _string(record.get("title")) or "Untitled announcement",
        "text": text,
        "html_url": safe_url(record.get("html_url"), base_url),
        "due_at": None,
        "posted_at": normalize_time(record.get("posted_at") or record.get("delayed_post_at") or record.get("created_at")),
        "action": None,
        "completed": 0,
        "missing": 0,
        "points_possible": None,
        "author": author_name or _string(record.get("user_name")),
        "links": dedupe_links(links),
    }


def _human_time(value: str | None) -> str:
    parsed = parse_time(value)
    if parsed is None:
        return "no due date"
    return f"{parsed:%b} {parsed.day}, {parsed.year} {parsed:%H:%M} UTC"


def _message(kind: str, course_label: str, item: dict) -> str:
    title = item["title"]
    if kind == "new_announcement":
        return f"New announcement in {course_label}: {title}"
    if kind == "new_assignment":
        due = f" (due {_human_time(item['due_at'])})" if item["due_at"] else ""
        return f"New assignment in {course_label}: {title}{due}"
    if kind == "due_date_changed":
        if item["due_at"] is None:
            return f"Due date removed in {course_label}: {title} no longer has a due date"
        return f"Due date changed in {course_label}: {title} is now due {_human_time(item['due_at'])}"
    return f"Assignment updated in {course_label}: {title}"


def _fetch_course(client, course_id: int, now: datetime) -> tuple[list[dict], list[dict]]:
    base_url = client.base_url
    assignments = [
        normalized
        for record in client.assignments(course_id, include_submission=True)
        if (normalized := normalize_assignment(record, base_url)) is not None
    ]
    announcements = [
        normalized
        for record in client.announcements(course_id, now - ANNOUNCEMENT_WINDOW, now)
        if (normalized := normalize_announcement(record, base_url)) is not None
    ]
    return assignments, announcements


def _upsert_course(connection: sqlite3.Connection, course_id: int, name: str, code: str | None):
    connection.execute(
        """INSERT INTO canvas_courses (id, name, course_code) VALUES (?, ?, ?)
           ON CONFLICT (id) DO UPDATE SET name = excluded.name, course_code = excluded.course_code""",
        (course_id, name, code),
    )


def _store_course(connection, course_id: int, course_label: str, items: list[dict], now: datetime, totals: dict):
    stamp = iso(now)
    baseline = connection.execute(
        "SELECT synced_at IS NULL FROM canvas_courses WHERE id = ?", (course_id,)
    ).fetchone()[0]
    recent_cutoff = iso(now - BASELINE_ANNOUNCEMENT_WINDOW)
    notifications: list[tuple[int, str, str]] = []
    for item in items:
        values = dict(item, course_id=course_id, links_json=json.dumps(item["links"]))
        existing = connection.execute(
            "SELECT * FROM canvas_items WHERE kind = ? AND source_id = ?", (item["kind"], item["source_id"])
        ).fetchone()
        if existing is None:
            columns = ("kind", "source_id", *_ITEM_FIELDS, "first_seen_at", "updated_at")
            row = {**values, "first_seen_at": stamp, "updated_at": stamp}
            cursor = connection.execute(
                f"INSERT INTO canvas_items ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [row[column] for column in columns],
            )
            totals["items_added"] += 1
            item_id = cursor.lastrowid
            if item["kind"] == "announcement":
                if not baseline or (item["posted_at"] is not None and item["posted_at"] >= recent_cutoff):
                    notifications.append((item_id, "new_announcement", _message("new_announcement", course_label, item)))
            elif not baseline:
                notifications.append((item_id, "new_assignment", _message("new_assignment", course_label, item)))
            continue

        changed = [field for field in _ITEM_FIELDS if existing[field] != values[field]]
        if not changed:
            continue
        connection.execute(
            f"UPDATE canvas_items SET {', '.join(f'{field} = ?' for field in changed)}, updated_at = ? WHERE id = ?",
            [values[field] for field in changed] + [stamp, existing["id"]],
        )
        totals["items_updated"] += 1
        if item["kind"] != "assignment":
            continue
        if "due_at" in changed:
            notifications.append((existing["id"], "due_date_changed", _message("due_date_changed", course_label, item)))
        if "title" in changed or "text" in changed:
            notifications.append((existing["id"], "assignment_updated", _message("assignment_updated", course_label, item)))

    connection.executemany(
        "INSERT INTO canvas_notifications (item_id, type, message, created_at) VALUES (?, ?, ?, ?)",
        [(item_id, kind, message, stamp) for item_id, kind, message in notifications],
    )
    totals["notifications_created"] += len(notifications)
    connection.execute("UPDATE canvas_courses SET synced_at = ? WHERE id = ?", (stamp, course_id))


def _transaction(connection: sqlite3.Connection, work, *args):
    connection.execute("BEGIN IMMEDIATE")
    try:
        work(connection, *args)
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def sync(connection: sqlite3.Connection, client, now: datetime | None = None) -> dict:
    """Sync every active course; return the contract's sync summary.

    Raises ``CourseListError`` when the course list cannot be read. Failures
    for one course are reported in ``errors`` and the remaining courses still
    sync. Database errors propagate.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    started_at = iso(now)
    clock = time.monotonic()
    try:
        courses = []
        for record in client.courses():
            course_id = _canvas_id(record)
            if course_id is None or record.get("access_restricted_by_date"):
                continue
            name = _string(record.get("name")) or f"Course {course_id}"
            courses.append((course_id, name, _string(record.get("course_code"))))
    except FETCH_ERRORS as error:
        raise CourseListError(f"Could not fetch the Canvas course list. {describe_error(error)}") from None

    totals = {"items_added": 0, "items_updated": 0, "notifications_created": 0}
    errors = []
    for course_id, name, code in courses:
        _transaction(connection, _upsert_course, course_id, name, code)
        try:
            assignments, announcements = _fetch_course(client, course_id, now)
        except FETCH_ERRORS as error:
            errors.append({"course_id": course_id, "course_name": name, "message": describe_error(error)})
            continue
        _transaction(connection, _store_course, course_id, code or name, assignments + announcements, now, totals)

    finished_at = iso(now + timedelta(seconds=round(time.monotonic() - clock)))
    _transaction(
        connection,
        lambda c: c.execute(
            "INSERT INTO canvas_state (key, value) VALUES ('last_synced_at', ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (finished_at,),
        ),
    )
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "courses": len(courses),
        **totals,
        "errors": errors,
    }
