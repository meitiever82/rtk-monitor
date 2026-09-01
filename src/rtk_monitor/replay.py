"""Rebuild the realtime WS message stream from SQLite for a time range (spec §6)."""
from __future__ import annotations

import asyncio
import dataclasses
import math

from rtk_monitor.storage.epochs import EpochStore
from rtk_monitor.storage.events import EventStore

_SRC_POS = ("can", "gpchc")


async def replay_messages(epochs: EpochStore, events: EventStore, t0: float, t1: float,
                          speed: float = 1.0, sleep=asyncio.sleep):
    """Async generator yielding messages isomorphic with the realtime WS stream.

    For each can/gpchc epoch → position message.
    For each whole second in [t0, t1] → status message with latest snapshots.
    For each event open/close action in range → event message.
    Ends with replay_end message.

    sleep can be injected for testing (e.g., async def nosleep(_): pass).
    """
    timeline: list[tuple[float, dict]] = []
    all_rows = {src: epochs.query(src, t0, t1) for src in ("rtkrcv", "can", "gpchc")}

    # Add position messages for can/gpchc sources.
    for src in _SRC_POS:
        for e in all_rows[src]:
            timeline.append((e.t, {"type": "position", "t": e.t, "src": src,
                                   "lat": e.lat, "lon": e.lon, "heading": e.heading,
                                   "q": e.q, "speed": e.speed}))

    # Add event messages (open and close actions).
    for row in events.query(since=t0):
        edict = {"t": row.t, "level": row.level, "code": row.code, "message": row.detail}
        if t0 <= row.t <= t1:
            timeline.append((row.t, {"type": "event", "t": row.t, "action": "open", "event": edict}))
        if row.t_close is not None and t0 <= row.t_close <= t1:
            timeline.append((row.t_close, {"type": "event", "t": row.t_close, "action": "close",
                                           "event": dict(edict, t=row.t_close)}))

    # Add status messages for each whole second in [t0, t1].
    for sec in range(math.ceil(t0), math.floor(t1) + 1):
        snap = {}
        for src in ("rtkrcv", "can", "gpchc"):
            rows = [e for e in all_rows[src] if e.t <= sec]
            snap[src] = dataclasses.asdict(rows[-1]) if rows else None
        timeline.append((float(sec), {
            "type": "status", "t": float(sec),
            "verdict": {"level": "info", "code": "replay", "message": "回放"},
            "sol": snap["rtkrcv"], "can": snap["can"], "gpchc": snap["gpchc"],
            "corr": {"last_t": None, "base_offset_m": None}}))

    # Sort timeline by time and yield messages with sleep delays.
    timeline.sort(key=lambda x: x[0])
    prev = t0
    for t, msg in timeline:
        if t > prev:
            await sleep((t - prev) / max(speed, 0.01))
        prev = t
        yield msg

    # End with replay_end message.
    yield {"type": "replay_end", "t": t1}
