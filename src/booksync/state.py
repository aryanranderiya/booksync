from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    sha256        TEXT PRIMARY KEY,
    volume_id     TEXT,
    title         TEXT NOT NULL,
    author        TEXT,
    fmt           TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    archive_path  TEXT NOT NULL,
    apple_key     TEXT,
    source        TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    imported_at   TEXT,
    status        TEXT NOT NULL,
    error         TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS books_volume ON books(volume_id) WHERE volume_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS skipped_volumes (
    volume_id TEXT PRIMARY KEY,
    title     TEXT,
    reason    TEXT NOT NULL,
    seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    fetched      INTEGER DEFAULT 0,
    imported     INTEGER DEFAULT 0,
    skipped      INTEGER DEFAULT 0,
    failed       INTEGER DEFAULT 0,
    note         TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Record:
    sha256: str
    title: str
    fmt: str
    bytes: int
    archive_path: str
    source: str
    status: str
    volume_id: str | None = None
    author: str | None = None
    apple_key: str | None = None
    downloaded_at: str | None = None
    imported_at: str | None = None
    error: str | None = None


class State:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "State":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def known_sha(self, sha: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM books WHERE sha256 = ?", (sha,)).fetchone()

    def known_volume(self, volume_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM books WHERE volume_id = ?", (volume_id,)).fetchone()

    def imported_keys(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT apple_key FROM books WHERE imported_at IS NOT NULL AND apple_key IS NOT NULL"
        ).fetchall()
        return {r["apple_key"] for r in rows}

    def known_volumes(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT volume_id FROM books WHERE volume_id IS NOT NULL"
        ).fetchall()
        return {r["volume_id"] for r in rows}

    def skipped_volumes(self) -> set[str]:
        rows = self.conn.execute("SELECT volume_id FROM skipped_volumes").fetchall()
        return {r["volume_id"] for r in rows}

    def skip_volume(self, volume_id: str, title: str | None, reason: str) -> None:
        self.conn.execute(
            """INSERT INTO skipped_volumes (volume_id, title, reason, seen_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(volume_id) DO UPDATE SET reason = excluded.reason,
                                                   seen_at = excluded.seen_at""",
            (volume_id, title, reason, now()),
        )
        self.conn.commit()

    def clear_skipped(self) -> None:
        self.conn.execute("DELETE FROM skipped_volumes")
        self.conn.commit()

    def add(self, rec: Record) -> None:
        self.conn.execute(
            """INSERT INTO books (sha256, volume_id, title, author, fmt, bytes, archive_path,
                                  apple_key, source, downloaded_at, imported_at, status, error)
               VALUES (:sha256, :volume_id, :title, :author, :fmt, :bytes, :archive_path,
                       :apple_key, :source, :downloaded_at, :imported_at, :status, :error)
               ON CONFLICT(sha256) DO UPDATE SET
                   volume_id = COALESCE(excluded.volume_id, books.volume_id),
                   archive_path = excluded.archive_path,
                   status = excluded.status""",
            {**rec.__dict__, "downloaded_at": rec.downloaded_at or now()},
        )
        self.conn.commit()

    def mark_imported(self, sha: str) -> None:
        self.conn.execute(
            "UPDATE books SET imported_at = ?, status = 'imported', error = NULL WHERE sha256 = ?",
            (now(), sha),
        )
        self.conn.commit()

    def mark_status(self, sha: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE books SET status = ?, error = ? WHERE sha256 = ?", (status, error, sha)
        )
        self.conn.commit()

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now(),))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, fetched: int, imported: int, skipped: int,
                   failed: int, note: str | None = None) -> None:
        self.conn.execute(
            """UPDATE runs SET finished_at = ?, fetched = ?, imported = ?, skipped = ?,
                               failed = ?, note = ? WHERE id = ?""",
            (now(), fetched, imported, skipped, failed, note, run_id),
        )
        self.conn.commit()

    def summary(self) -> dict:
        row = self.conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN imported_at IS NOT NULL THEN 1 ELSE 0 END) AS imported,
                      SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
               FROM books"""
        ).fetchone()
        last = self.conn.execute(
            "SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {"total": row["total"], "imported": row["imported"] or 0,
                "failed": row["failed"] or 0, "last_run": last}
