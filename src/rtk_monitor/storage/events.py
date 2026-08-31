"""SQLite-backed event log. Plan 2's diagnosis engine extends this table."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    t REAL NOT NULL,
    etype TEXT NOT NULL,
    state TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_t ON events(t);"""


@dataclass(frozen=True)
class EventRow:
    id: int
    t: float
    etype: str
    state: str
    detail: str


class EventStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db = sqlite3.connect(db_path)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def record(self, t: float, etype: str, state: str, detail: str = "") -> int:
        cur = self._db.execute(
            "INSERT INTO events (t, etype, state, detail) VALUES (?, ?, ?, ?)",
            (t, etype, state, detail))
        self._db.commit()
        return int(cur.lastrowid)

    def query(self, since: float = 0.0) -> list[EventRow]:
        rows = self._db.execute(
            "SELECT id, t, etype, state, detail FROM events WHERE t >= ? ORDER BY t",
            (since,)).fetchall()
        return [EventRow(*r) for r in rows]

    def close(self) -> None:
        self._db.close()
