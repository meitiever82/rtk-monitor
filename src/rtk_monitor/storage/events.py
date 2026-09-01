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

_EXTRA_COLS = (("level", "TEXT"), ("code", "TEXT"), ("t_close", "REAL"),
               ("lat", "REAL"), ("lon", "REAL"),
               ("lat_close", "REAL"), ("lon_close", "REAL"), ("peak", "TEXT"))


@dataclass(frozen=True)
class EventRow:
    id: int
    t: float
    etype: str
    state: str
    detail: str
    level: str | None = None
    code: str | None = None
    t_close: float | None = None
    lat: float | None = None
    lon: float | None = None
    lat_close: float | None = None
    lon_close: float | None = None
    peak: str | None = None


class EventStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db = sqlite3.connect(db_path)
        self._db.executescript(_SCHEMA)
        self._db.commit()
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(events)")}
        for col, typ in _EXTRA_COLS:
            if col not in cols:
                self._db.execute(f"ALTER TABLE events ADD COLUMN {col} {typ}")
        self._db.commit()

    def record(self, t: float, etype: str, state: str, detail: str = "",
               level: str | None = None, code: str | None = None,
               lat: float | None = None, lon: float | None = None) -> int:
        cur = self._db.execute(
            "INSERT INTO events (t, etype, state, detail, level, code, lat, lon)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (t, etype, state, detail, level, code, lat, lon))
        self._db.commit()
        return int(cur.lastrowid)

    def query(self, since: float = 0.0) -> list[EventRow]:
        rows = self._db.execute(
            "SELECT id, t, etype, state, detail, level, code, t_close, lat, lon, lat_close, lon_close, peak"
            " FROM events WHERE t >= ? ORDER BY t",
            (since,)).fetchall()
        return [EventRow(*r) for r in rows]

    def close_event(self, event_id: int, t_close: float, lat: float | None = None,
                    lon: float | None = None, peak: str | None = None) -> None:
        self._db.execute(
            "UPDATE events SET state='closed', t_close=?, lat_close=?, lon_close=?, peak=?"
            " WHERE id=?", (t_close, lat, lon, peak, event_id))
        self._db.commit()

    def prune(self, before_t: float) -> int:
        cur = self._db.execute(
            "DELETE FROM events WHERE state='closed' AND t < ?", (before_t,))
        self._db.commit()
        return cur.rowcount

    def close(self) -> None:
        self._db.close()
