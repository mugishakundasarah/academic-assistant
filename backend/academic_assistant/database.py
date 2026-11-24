"""SQLite schema migrations for local development."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path


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
        connection.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (1)")


def schema_version(path: Path) -> int:
    uri = path.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if version != 1:
            raise sqlite3.DatabaseError("Unsupported or missing schema version")
        return version
