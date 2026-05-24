from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


class DealStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen_items (
                item_id TEXT PRIMARY KEY,
                search_id TEXT NOT NULL,
                alerted_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_cursors (
                search_id TEXT PRIMARY KEY,
                newest_listed_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def has_seen(self, item_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return row is not None

    def mark_seen(self, item_id: str, search_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_items (item_id, search_id, alerted_at) VALUES (?, ?, ?)",
            (item_id, search_id, datetime.utcnow().isoformat()),
        )
        self._conn.commit()

    def get_cursor(self, search_id: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT newest_listed_at FROM search_cursors WHERE search_id = ?",
            (search_id,),
        ).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row["newest_listed_at"])

    def update_cursor(self, search_id: str, listed_at: datetime) -> None:
        existing = self.get_cursor(search_id)
        if existing and listed_at <= existing:
            return
        self._conn.execute(
            """
            INSERT INTO search_cursors (search_id, newest_listed_at)
            VALUES (?, ?)
            ON CONFLICT(search_id) DO UPDATE SET newest_listed_at = excluded.newest_listed_at
            """,
            (search_id, listed_at.isoformat()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
