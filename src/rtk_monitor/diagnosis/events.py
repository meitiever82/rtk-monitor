"""Open/close diagnosis events with close hysteresis (spec §4.3)."""
from __future__ import annotations

from typing import Callable

from rtk_monitor.diagnosis.rules import Verdict
from rtk_monitor.storage.events import EventStore

_OPEN_LEVELS = {"warning", "serious", "critical"}
OnTransition = Callable[[str, Verdict, float], None]


class EventMachine:
    def __init__(self, store: EventStore, close_hysteresis_s: float = 10.0,
                 on_transition: OnTransition | None = None) -> None:
        self._store = store
        self._hyst = close_hysteresis_s
        self._cb = on_transition
        self._open_id: int | None = None
        self._open_code: str | None = None
        self._open_verdict: Verdict | None = None
        self._ok_since: float | None = None

    def update(self, t: float, verdict: Verdict,
               lat: float | None = None, lon: float | None = None) -> None:
        active = verdict.level in _OPEN_LEVELS
        if active:
            self._ok_since = None
            if self._open_code == verdict.code:
                return
            if self._open_id is not None:            # different condition: close old
                self._close(t)
            self._open_id = self._store.record(
                t, "diagnosis", "open", verdict.message,
                level=verdict.level, code=verdict.code, lat=lat, lon=lon)
            self._open_code = verdict.code
            self._open_verdict = verdict
            if self._cb:
                self._cb("open", verdict, t)
            return
        # ok/info: close after hysteresis
        if self._open_id is None:
            return
        if self._ok_since is None:
            self._ok_since = t
            return
        if t - self._ok_since >= self._hyst:
            self._close(t)

    def _close(self, t: float) -> None:
        assert self._open_id is not None and self._open_verdict is not None
        self._store.close_event(self._open_id, t)
        if self._cb:
            self._cb("close", self._open_verdict, t)
        self._open_id = self._open_code = self._open_verdict = None
        self._ok_since = None
