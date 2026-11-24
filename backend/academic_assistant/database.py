"""SQLite schema migrations for local development.

Migrations are an ordered list of ``(version, statements)`` pairs. ``migrate``
applies every version that is not yet recorded in ``schema_migrations`` inside
one ``BEGIN IMMEDIATE`` transaction, so an existing database is upgraded in
place and running it again is a no-op. Append new versions to ``MIGRATIONS``;
never edit a version that has shipped.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    # Version 1 only creates the migration ledger itself.
    (1, ()),
    # Version 2 stores synced Canvas courses, assignments, announcements, and
    # in-app notifications. Course IDs are Canvas course IDs.
    (
        2,
        (
            """CREATE TABLE canvas_courses (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                course_code TEXT,
                synced_at TEXT
            )""",
            """CREATE TABLE canvas_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK (kind IN ('assignment', 'announcement')),
                source_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL REFERENCES canvas_courses (id),
                title TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                html_url TEXT,
                due_at TEXT,
                posted_at TEXT,
                action TEXT CHECK (action IN ('read', 'submit', 'quiz', 'discussion')),
                completed INTEGER NOT NULL DEFAULT 0,
                missing INTEGER NOT NULL DEFAULT 0,
                points_possible REAL,
                author TEXT,
                links_json TEXT NOT NULL DEFAULT '[]',
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (kind, source_id)
            )""",
            "CREATE INDEX canvas_items_course ON canvas_items (course_id, kind)",
            "CREATE INDEX canvas_items_due ON canvas_items (kind, completed, due_at)",
            """CREATE TABLE canvas_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES canvas_items (id),
                type TEXT NOT NULL CHECK (type IN (
                    'new_announcement', 'new_assignment', 'due_date_changed', 'assignment_updated'
                )),
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT
            )""",
            "CREATE INDEX canvas_notifications_unread ON canvas_notifications (read_at, created_at)",
            """CREATE TABLE canvas_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""",
        ),
    ),
    # Version 3 snapshots the item's due date when a notification is created,
    # so old notifications keep the date they announced. Existing rows get NULL.
    (3, ("ALTER TABLE canvas_notifications ADD COLUMN due_at TEXT",)),
)

LATEST_VERSION = MIGRATIONS[-1][0]


def database_path() -> Path:
    return Path(os.environ.get("SQLITE_PATH", "instance/academic.sqlite3"))


def migrate(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        for version, statements in MIGRATIONS:
            if version in applied:
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))


def schema_version(path: Path) -> int:
    uri = path.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if version != LATEST_VERSION:
            raise sqlite3.DatabaseError("Unsupported or missing schema version")
        return version


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection for one request or job.

    The connection is in autocommit mode (callers use explicit ``BEGIN``),
    returns ``sqlite3.Row`` rows, and enforces foreign keys. It may be used
    from a different thread than the one that opened it, but never
    concurrently.
    """
    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
