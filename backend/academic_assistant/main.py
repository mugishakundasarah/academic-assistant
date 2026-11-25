"""Academic Assistant HTTP entry point."""

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from . import ed_sync
from .canvas_sync import CourseListError, iso, sync
from .database import connect, database_path, migrate, schema_version
from .env import BACKEND_ENV_FILE, load_env_file  # noqa: F401 (re-exported for callers)
from .integrations.canvas import CanvasClient
from .integrations.canvas_demo import DemoCanvasClient
from .integrations.ed import EdClient
from .integrations.ed_demo import DemoEdClient

OVERDUE_WINDOW = timedelta(days=14)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_env_file()
    app.state.database_path = database_path()
    migrate(app.state.database_path)
    yield


app = FastAPI(title="Academic Assistant", lifespan=lifespan)
sync_lock = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def get_db() -> Iterator[sqlite3.Connection]:
    with closing(connect(app.state.database_path)) as connection:
        yield connection


DB = Annotated[sqlite3.Connection, Depends(get_db)]
# SQLite integers are signed 64-bit; larger path ids would overflow, so reject them with 422.
Id = Annotated[int, PathParam(ge=1, le=2**63 - 1)]


def demo_enabled() -> bool:
    return os.environ.get("CANVAS_DEMO", "").strip().lower() in ("1", "true", "yes")


def live_client() -> CanvasClient:
    """Build the live client from the environment; raises ValueError with a safe message."""
    return CanvasClient(os.environ.get("CANVAS_BASE_URL", ""), os.environ.get("CANVAS_API_TOKEN", ""))


def live_configured() -> bool:
    try:
        live_client()
    except ValueError:
        return False
    return True


def ed_live_client() -> EdClient:
    """Build the live Ed client; raises ValueError with a safe message."""
    return EdClient(os.environ.get("ED_API_TOKEN", ""), os.environ.get("ED_REGION", ""))


def ed_live_configured() -> bool:
    try:
        ed_live_client()
    except ValueError:
        return False
    return True


def _state(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM canvas_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_state(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO canvas_state (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ---------------------------------------------------------------- course matching


def course_matches(connection: sqlite3.Connection) -> tuple[dict[int, int], dict[int, int]]:
    """Return ``(canvas_id -> ed_id, ed_id -> canvas_id)``.

    A Canvas and an Ed course match when ``normalize_course_code`` of their
    codes (falling back to the name) is equal. Matching is one to one: when
    several courses on one side share a code, the most recently synced one
    (then the highest id) is matched and the others stay unmatched.
    """
    def pick(rows, code_column):
        chosen: dict[str, sqlite3.Row] = {}
        for row in rows:
            key = ed_sync.normalize_course_code(row[code_column]) or ed_sync.normalize_course_code(row["name"])
            if key is None:
                continue
            best = chosen.get(key)
            if best is None or (row["synced_at"] or "", row["id"]) > (best["synced_at"] or "", best["id"]):
                chosen[key] = row
        return chosen

    canvas = pick(connection.execute("SELECT id, name, course_code, synced_at FROM canvas_courses"), "course_code")
    ed = pick(connection.execute("SELECT id, name, code, synced_at FROM ed_courses"), "code")
    canvas_to_ed = {canvas[key]["id"]: ed[key]["id"] for key in canvas.keys() & ed.keys()}
    return canvas_to_ed, {ed_id: canvas_id for canvas_id, ed_id in canvas_to_ed.items()}


# ---------------------------------------------------------------- serializers

_ITEM_SELECT = """SELECT i.*, c.name AS course_name
                  FROM canvas_items i JOIN canvas_courses c ON c.id = i.course_id"""


def item_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "course_id": row["course_id"],
        "course_name": row["course_name"],
        "title": row["title"],
        "text": row["text"],
        "html_url": row["html_url"],
        "due_at": row["due_at"],
        "posted_at": row["posted_at"],
        "action": row["action"],
        "completed": bool(row["completed"]),
        "missing": bool(row["missing"]),
        "points_possible": row["points_possible"],
        "author": row["author"],
        "links": json.loads(row["links_json"]),
        "platform": row["platform"],
        "first_seen_at": row["first_seen_at"],
        "updated_at": row["updated_at"],
    }


def course_json(connection: sqlite3.Connection, row: sqlite3.Row, now: str, canvas_to_ed: dict[int, int]) -> dict:
    stats = connection.execute(
        """SELECT
             COALESCE(SUM(kind = 'assignment' AND completed = 0 AND (due_at IS NULL OR due_at >= :now)), 0),
             MIN(CASE WHEN kind = 'assignment' AND completed = 0 AND due_at >= :now THEN due_at END)
           FROM canvas_items WHERE course_id = :course""",
        {"now": now, "course": row["id"]},
    ).fetchone()
    unread = connection.execute(
        """SELECT COUNT(*) FROM canvas_notifications n JOIN canvas_items i ON i.id = n.item_id
           WHERE i.course_id = ? AND n.read_at IS NULL""",
        (row["id"],),
    ).fetchone()[0]
    ed_course_id = canvas_to_ed.get(row["id"])
    if ed_course_id is not None:
        unread += connection.execute(
            """SELECT COUNT(*) FROM canvas_notifications n JOIN ed_threads t ON t.id = n.ed_thread_id
               WHERE t.ed_course_id = ? AND n.read_at IS NULL""",
            (ed_course_id,),
        ).fetchone()[0]
    return {
        "id": row["id"],
        "name": row["name"],
        "course_code": row["course_code"],
        "synced_at": row["synced_at"],
        "open_count": stats[0],
        "next_due_at": stats[1],
        "unread_count": unread,
        "ed_course_id": ed_course_id,
    }


def ed_course_json(row: sqlite3.Row, ed_to_canvas: dict[int, int]) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "url": row["url"],
        "synced_at": row["synced_at"],
        "canvas_course_id": ed_to_canvas.get(row["id"]),
    }


_ED_THREAD_COLUMNS = (
    "id", "ed_course_id", "title", "type", "category", "created_at", "is_pinned", "is_answered", "text", "url",
    "first_seen_at",
)


def ed_thread_json(row: sqlite3.Row, prefix: str = "") -> dict:
    thread = {column: row[prefix + column] for column in _ED_THREAD_COLUMNS}
    thread["is_pinned"] = bool(thread["is_pinned"])
    thread["is_answered"] = bool(thread["is_answered"])
    thread["text"] = thread["text"] or ""
    return thread


def ed_threads(connection: sqlite3.Connection, ed_course_id: int) -> list[dict]:
    """Pinned threads, then announcements from the last 30 days, newest first."""
    cutoff = iso(utc_now() - ed_sync.THREAD_WINDOW)
    rows = connection.execute(
        """SELECT * FROM ed_threads WHERE ed_course_id = ?
             AND (is_pinned = 1 OR (type = 'announcement' AND created_at >= ?))
           ORDER BY is_pinned DESC, created_at DESC, id DESC""",
        (ed_course_id, cutoff),
    ).fetchall()
    return [ed_thread_json(row) for row in rows]


_NOTIFICATION_SELECT = f"""SELECT n.id AS notification_id, n.type, n.message, n.created_at, n.read_at,
                                 n.due_at AS notification_due_at, n.item_id AS notification_item_id,
                                 i.*, c.name AS course_name,
                                 {", ".join(f"t.{column} AS ed_{column}" for column in _ED_THREAD_COLUMNS)},
                                 e.id AS edc_id, e.code AS edc_code, e.name AS edc_name, e.url AS edc_url,
                                 e.synced_at AS edc_synced_at
                          FROM canvas_notifications n
                          LEFT JOIN canvas_items i ON i.id = n.item_id
                          LEFT JOIN canvas_courses c ON c.id = i.course_id
                          LEFT JOIN ed_threads t ON t.id = n.ed_thread_id
                          LEFT JOIN ed_courses e ON e.id = t.ed_course_id"""


def notification_json(row: sqlite3.Row, ed_to_canvas: dict[int, int]) -> dict:
    """``item`` is null for Ed notifications; ``ed_thread`` and ``ed_course`` are null for Canvas ones."""
    ed = row["ed_id"] is not None
    return {
        "id": row["notification_id"],
        "type": row["type"],
        "message": row["message"],
        "created_at": row["created_at"],
        "read_at": row["read_at"],
        "due_at": row["notification_due_at"],
        "item": item_json(row) if row["notification_item_id"] is not None else None,
        "ed_thread": ed_thread_json(row, "ed_") if ed else None,
        "ed_course": ed_course_json(
            {key[4:]: row[key] for key in ("edc_id", "edc_code", "edc_name", "edc_url", "edc_synced_at")},
            ed_to_canvas,
        ) if ed else None,
    }


def _course_row(connection: sqlite3.Connection, course_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM canvas_courses WHERE id = ?", (course_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    return row


def _ed_course_row(connection: sqlite3.Connection, ed_course_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM ed_courses WHERE id = ?", (ed_course_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Ed course not found.")
    return row


def _notification(connection: sqlite3.Connection, notification_id: int) -> sqlite3.Row:
    row = connection.execute(f"{_NOTIFICATION_SELECT} WHERE n.id = ?", (notification_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return row


# ---------------------------------------------------------------- endpoints


@app.get("/health")
def health():
    try:
        version = schema_version(app.state.database_path)
    except sqlite3.Error:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok", "schema_version": version}


@app.get("/api/canvas/status")
def canvas_status(connection: DB):
    return {
        "configured": live_configured(),
        "demo": demo_enabled(),
        "syncing": sync_lock.locked(),
        "last_synced_at": _state(connection, "last_synced_at"),
    }


def _run_canvas_sync(connection: sqlite3.Connection, now: datetime) -> dict:
    """Run the Canvas sync (demo or live); raises ValueError (not configured) or CourseListError."""
    demo = demo_enabled()
    if demo:
        demo_syncs = int(_state(connection, "demo_syncs") or 0)
        client = DemoCanvasClient(now=now, sync_number=demo_syncs + 1)
    else:
        client = live_client()
    result = sync(connection, client, now)
    if demo:
        _set_state(connection, "demo_syncs", str(demo_syncs + 1))
    return result


def _run_ed_sync(connection: sqlite3.Connection, now: datetime) -> dict:
    """Run the Ed sync (demo when CANVAS_DEMO is on); raises ValueError or EdCourseListError."""
    demo = demo_enabled()
    if demo:
        demo_syncs = int(_state(connection, "ed_demo_syncs") or 0)
        client = DemoEdClient(now=now, sync_number=demo_syncs + 1)
    else:
        client = ed_live_client()
    result = ed_sync.sync(connection, client, now)
    if demo:
        _set_state(connection, "ed_demo_syncs", str(demo_syncs + 1))
    return result


@app.post("/api/canvas/sync")
def canvas_sync(connection: DB):
    # A plain ``def`` endpoint runs in the threadpool, so the blocking Canvas
    # requests do not stall the event loop. The lock allows one sync at a time.
    if not sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A Canvas sync is already running.")
    try:
        try:
            return _run_canvas_sync(connection, utc_now())
        except ValueError as error:
            raise HTTPException(
                status_code=503,
                detail=f"Canvas is not configured: {error}. Set CANVAS_DEMO=1 to try the demo data.",
            ) from None
        except CourseListError as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
    finally:
        sync_lock.release()


@app.post("/api/sync")
def sync_all(connection: DB):
    """Sync Canvas, then Ed, each only when configured (or in demo mode).

    A source whose course list cannot be read is reported in its own
    ``errors`` (with ``course_id`` null); the response is 502 only when every
    source that ran failed that way.
    """
    demo = demo_enabled()
    run_canvas = demo or live_configured()
    run_ed = demo or ed_live_configured()
    if not run_canvas and not run_ed:
        raise HTTPException(
            status_code=503,
            detail="Neither Canvas nor Ed is configured. Set CANVAS_BASE_URL and CANVAS_API_TOKEN, "
                   "ED_API_TOKEN, or CANVAS_DEMO=1 to try the demo data.",
        )
    if not sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A sync is already running.")
    try:
        now = utc_now()
        failures = []
        canvas = ed = None
        if run_canvas:
            try:
                canvas = _run_canvas_sync(connection, now)
            except CourseListError as error:
                failures.append(str(error))
                canvas = {
                    "started_at": iso(now), "finished_at": iso(now), "courses": 0, "items_added": 0,
                    "items_updated": 0, "notifications_created": 0,
                    "errors": [{"course_id": None, "course_name": None, "message": str(error)}],
                }
        if run_ed:
            try:
                ed = _run_ed_sync(connection, now)
            except ed_sync.EdCourseListError as error:
                failures.append(str(error))
                ed = {"courses": 0, "threads_added": 0, "threads_updated": 0, "notifications_created": 0,
                      "errors": [{"course_id": None, "course_name": None, "message": str(error)}]}
        if len(failures) == run_canvas + run_ed:
            raise HTTPException(status_code=502, detail=" ".join(failures))
        return {"canvas": canvas, "ed": ed}
    finally:
        sync_lock.release()


@app.get("/api/ed/status")
def ed_status(connection: DB):
    return {
        "configured": ed_live_configured(),
        "demo": demo_enabled(),
        "last_synced_at": _state(connection, "ed_last_synced_at"),
    }


@app.get("/api/ed/courses")
def list_ed_courses(connection: DB):
    _, ed_to_canvas = course_matches(connection)
    rows = connection.execute("SELECT * FROM ed_courses ORDER BY code COLLATE NOCASE, name COLLATE NOCASE, id")
    return {"courses": [ed_course_json(row, ed_to_canvas) for row in rows]}


@app.get("/api/ed/courses/{ed_course_id}")
def get_ed_course(ed_course_id: Id, connection: DB):
    row = _ed_course_row(connection, ed_course_id)
    _, ed_to_canvas = course_matches(connection)
    return {"ed_course": ed_course_json(row, ed_to_canvas), "threads": ed_threads(connection, ed_course_id)}


@app.get("/api/courses")
def list_courses(connection: DB):
    now = iso(utc_now())
    rows = connection.execute("SELECT * FROM canvas_courses ORDER BY name COLLATE NOCASE, id").fetchall()
    canvas_to_ed, _ = course_matches(connection)
    return {"courses": [course_json(connection, row, now, canvas_to_ed) for row in rows]}


@app.get("/api/courses/{course_id}")
def get_course(course_id: Id, connection: DB):
    row = _course_row(connection, course_id)
    return course_json(connection, row, iso(utc_now()), course_matches(connection)[0])


@app.get("/api/courses/{course_id}/ed")
def course_ed(course_id: Id, connection: DB):
    _course_row(connection, course_id)
    canvas_to_ed, ed_to_canvas = course_matches(connection)
    ed_course_id = canvas_to_ed.get(course_id)
    if ed_course_id is None:
        return {"ed_course": None, "threads": []}
    row = _ed_course_row(connection, ed_course_id)
    return {"ed_course": ed_course_json(row, ed_to_canvas), "threads": ed_threads(connection, ed_course_id)}


@app.get("/api/courses/{course_id}/items")
def course_items(
    course_id: Id,
    connection: DB,
    kind: Literal["assignment", "announcement"] | None = None,
):
    _course_row(connection, course_id)
    items = []
    if kind in (None, "assignment"):
        items += connection.execute(
            f"""{_ITEM_SELECT} WHERE i.course_id = ? AND i.kind = 'assignment'
                ORDER BY i.completed,
                         CASE WHEN i.completed = 0 THEN i.due_at IS NULL END,
                         CASE WHEN i.completed = 0 THEN i.due_at END ASC,
                         CASE WHEN i.completed = 1 THEN i.due_at END DESC,
                         i.id""",
            (course_id,),
        ).fetchall()
    if kind in (None, "announcement"):
        items += connection.execute(
            f"""{_ITEM_SELECT} WHERE i.course_id = ? AND i.kind = 'announcement'
                ORDER BY i.posted_at DESC, i.id DESC""",
            (course_id,),
        ).fetchall()
    return {"items": [item_json(row) for row in items]}


@app.get("/api/upcoming")
def upcoming(connection: DB, limit: Annotated[int, Query(ge=1, le=50)] = 10):
    now = utc_now()
    pending = f"{_ITEM_SELECT} WHERE i.kind = 'assignment' AND i.completed = 0"
    upcoming_rows = connection.execute(
        f"{pending} AND i.due_at >= ? ORDER BY i.due_at, i.id LIMIT ?", (iso(now), limit)
    ).fetchall()
    overdue_rows = connection.execute(
        f"{pending} AND i.due_at >= ? AND i.due_at < ? ORDER BY i.due_at DESC, i.id",
        (iso(now - OVERDUE_WINDOW), iso(now)),
    ).fetchall()
    return {
        "overdue": [item_json(row) for row in overdue_rows],
        "upcoming": [item_json(row) for row in upcoming_rows],
    }


@app.get("/api/notifications")
def list_notifications(
    connection: DB,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    where = " WHERE n.read_at IS NULL" if unread_only else ""
    rows = connection.execute(
        f"{_NOTIFICATION_SELECT}{where} ORDER BY n.created_at DESC, n.id DESC LIMIT ?", (limit,)
    ).fetchall()
    unread = connection.execute("SELECT COUNT(*) FROM canvas_notifications WHERE read_at IS NULL").fetchone()[0]
    _, ed_to_canvas = course_matches(connection)
    return {"notifications": [notification_json(row, ed_to_canvas) for row in rows], "unread_count": unread}


@app.post("/api/notifications/read-all")
def read_all_notifications(connection: DB):
    cursor = connection.execute(
        "UPDATE canvas_notifications SET read_at = ? WHERE read_at IS NULL", (iso(utc_now()),)
    )
    return {"updated": cursor.rowcount}


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: Id, connection: DB):
    _notification(connection, notification_id)
    connection.execute(
        "UPDATE canvas_notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
        (iso(utc_now()), notification_id),
    )
    return notification_json(_notification(connection, notification_id), course_matches(connection)[1])
