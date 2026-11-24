"""Academic Assistant HTTP entry point."""

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from .canvas_sync import CourseListError, iso, sync
from .database import connect, database_path, migrate, schema_version
from .integrations.canvas import CanvasClient
from .integrations.canvas_demo import DemoCanvasClient

BACKEND_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
OVERDUE_WINDOW = timedelta(days=14)


def load_env_file(path: Path = BACKEND_ENV_FILE) -> bool:
    """Load ``backend/.env`` if python-dotenv is installed. Real environment variables win."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    return load_dotenv(path, override=False)


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


def _state(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM canvas_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


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
        "first_seen_at": row["first_seen_at"],
        "updated_at": row["updated_at"],
    }


def course_json(connection: sqlite3.Connection, row: sqlite3.Row, now: str) -> dict:
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
    return {
        "id": row["id"],
        "name": row["name"],
        "course_code": row["course_code"],
        "synced_at": row["synced_at"],
        "open_count": stats[0],
        "next_due_at": stats[1],
        "unread_count": unread,
    }


_NOTIFICATION_SELECT = """SELECT n.id AS notification_id, n.type, n.message, n.created_at, n.read_at,
                                 n.due_at AS notification_due_at,
                                 i.*, c.name AS course_name
                          FROM canvas_notifications n
                          JOIN canvas_items i ON i.id = n.item_id
                          JOIN canvas_courses c ON c.id = i.course_id"""


def notification_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["notification_id"],
        "type": row["type"],
        "message": row["message"],
        "created_at": row["created_at"],
        "read_at": row["read_at"],
        "due_at": row["notification_due_at"],
        "item": item_json(row),
    }


def _course_row(connection: sqlite3.Connection, course_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM canvas_courses WHERE id = ?", (course_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Course not found.")
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


@app.post("/api/canvas/sync")
def canvas_sync(connection: DB):
    # A plain ``def`` endpoint runs in the threadpool, so the blocking Canvas
    # requests do not stall the event loop. The lock allows one sync at a time.
    if not sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A Canvas sync is already running.")
    try:
        now = utc_now()
        demo = demo_enabled()
        if demo:
            demo_syncs = int(_state(connection, "demo_syncs") or 0)
            client = DemoCanvasClient(now=now, sync_number=demo_syncs + 1)
        else:
            try:
                client = live_client()
            except ValueError as error:
                raise HTTPException(
                    status_code=503,
                    detail=f"Canvas is not configured: {error}. Set CANVAS_DEMO=1 to try the demo data.",
                ) from None
        try:
            result = sync(connection, client, now)
        except CourseListError as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        if demo:
            connection.execute(
                "INSERT INTO canvas_state (key, value) VALUES ('demo_syncs', ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (str(demo_syncs + 1),),
            )
        return result
    finally:
        sync_lock.release()


@app.get("/api/courses")
def list_courses(connection: DB):
    now = iso(utc_now())
    rows = connection.execute("SELECT * FROM canvas_courses ORDER BY name COLLATE NOCASE, id").fetchall()
    return {"courses": [course_json(connection, row, now) for row in rows]}


@app.get("/api/courses/{course_id}")
def get_course(course_id: Id, connection: DB):
    return course_json(connection, _course_row(connection, course_id), iso(utc_now()))


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
    return {"notifications": [notification_json(row) for row in rows], "unread_count": unread}


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
    return notification_json(_notification(connection, notification_id))
