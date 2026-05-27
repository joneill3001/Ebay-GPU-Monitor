from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator


class DealStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS seen_items (
                item_id TEXT PRIMARY KEY,
                search_id TEXT NOT NULL,
                alerted_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_cursors (
                search_id TEXT PRIMARY KEY,
                newest_listed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_usage (
                date TEXT PRIMARY KEY,
                call_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS near_misses (
                item_id TEXT PRIMARY KEY,
                search_id TEXT NOT NULL,
                title TEXT NOT NULL,
                price REAL NOT NULL,
                target_price REAL NOT NULL,
                url TEXT NOT NULL,
                listed_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group writes; one commit on success."""
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def has_seen(self, item_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return row is not None

    def filter_seen_ids(self, item_ids: list[str]) -> set[str]:
        """Return the subset of item_ids already in seen_items (single query)."""
        if not item_ids:
            return set()
        placeholders = ",".join("?" for _ in item_ids)
        rows = self._conn.execute(
            f"SELECT item_id FROM seen_items WHERE item_id IN ({placeholders})",
            item_ids,
        ).fetchall()
        return {row["item_id"] for row in rows}

    def mark_seen(self, item_id: str, search_id: str, *, commit: bool = True) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_items (item_id, search_id, alerted_at) VALUES (?, ?, ?)",
            (item_id, search_id, datetime.now(timezone.utc).isoformat()),
        )
        if commit:
            self._conn.commit()

    def get_cursor(self, search_id: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT newest_listed_at FROM search_cursors WHERE search_id = ?",
            (search_id,),
        ).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row["newest_listed_at"])

    def update_cursor(
        self, search_id: str, listed_at: datetime, *, commit: bool = True
    ) -> None:
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
        if commit:
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _get_today_date(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def increment_api_calls(self, count: int = 1) -> None:
        if count < 1 or count > 100:
            raise ValueError(f"api call increment must be 1–100, got {count}")
        today = self._get_today_date()
        self._conn.execute(
            """
            INSERT INTO api_usage (date, call_count) VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET call_count = call_count + excluded.call_count
            """,
            (today, count),
        )
        self._conn.commit()

    def get_today_api_calls(self) -> int:
        today = self._get_today_date()
        row = self._conn.execute(
            "SELECT call_count FROM api_usage WHERE date = ?",
            (today,),
        ).fetchone()
        return int(row["call_count"]) if row else 0

    def add_near_miss(
        self,
        item_id: str,
        search_id: str,
        title: str,
        price: float,
        target_price: float,
        url: str,
        listed_at: datetime,
        *,
        commit: bool = True,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO near_misses
            (item_id, search_id, title, price, target_price, url, listed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                search_id,
                title[:512],
                price,
                target_price,
                url[:2048],
                listed_at.isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        if commit:
            self._conn.commit()

    def get_recent_near_misses(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        rows = self._conn.execute(
            """
            SELECT item_id, search_id, title, price, target_price, url, listed_at, created_at
            FROM near_misses
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def cleanup_old_near_misses(self, days: int = 7) -> int:
        safe_days = max(1, min(int(days), 365))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM near_misses WHERE created_at < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount
