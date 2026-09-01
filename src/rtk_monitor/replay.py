"""Rebuild the realtime WS message stream from SQLite for a time range (spec §6)."""
from __future__ import annotations

import asyncio
import dataclasses
import math

from rtk_monitor.storage.epochs import EpochStore
from rtk_monitor.storage.events import EventStore

_SRC_POS = ("can", "gpchc")
_SRC_ALL = ("rtkrcv", "can", "gpchc")

# How far back of [t0, t1] to pull epochs purely for snapshot carry-forward
# (status.sol/can/gpchc must reflect the most recent epoch known as of each
# second, even if that epoch was written before the replay window started).
_SNAPSHOT_LOOKBACK_S = 600.0


async def replay_messages(epochs: EpochStore, events: EventStore, t0: float, t1: float,
                          speed: float = 1.0, sleep=asyncio.sleep):
    """Async generator yielding messages isomorphic with the realtime WS stream.

    For each can/gpchc epoch within [t0, t1] -> position message.
    For each whole second in [t0, t1] -> status message with latest snapshots,
    carried forward from up to _SNAPSHOT_LOOKBACK_S before t0 if needed.
    For each event open/close action within [t0, t1] -> event message.
    Ends with replay_end message.

    sleep can be injected for testing (e.g., async def nosleep(_): pass).
    """
    timeline: list[tuple[float, dict]] = []

    # Rows used for snapshot carry-forward (status.sol/can/gpchc) reach back
    # _SNAPSHOT_LOOKBACK_S before t0 so a status message near t0 can still
    # reflect an epoch written just before the window opened.
    snapshot_rows = {src: epochs.query(src, t0 - _SNAPSHOT_LOOKBACK_S, t1) for src in _SRC_ALL}

    # Position messages are only emitted for epochs that actually fall inside
    # the replay window -- carry-forward is a snapshot-only concept.
    for src in _SRC_POS:
        for e in snapshot_rows[src]:
            if t0 <= e.t <= t1:
                timeline.append((e.t, {"type": "position", "t": e.t, "src": src,
                                       "lat": e.lat, "lon": e.lon, "heading": e.heading,
                                       "q": e.q, "speed": e.speed}))

    # Event messages: query the full history (not just since=t0) so an event
    # opened before t0 but closed inside [t0, t1] still produces its close
    # message. Open/close actions are then independently window-filtered in
    # Python -- filtering "open" at the SQL level (since=t0) would silently
    # drop the close action for any event that started before the window.
    for row in events.query(since=0.0):
        edict = {"t": row.t, "level": row.level, "code": row.code, "message": row.detail}
        if t0 <= row.t <= t1:
            timeline.append((row.t, {"type": "event", "t": row.t, "action": "open", "event": edict}))
        if row.t_close is not None and t0 <= row.t_close <= t1:
            timeline.append((row.t_close, {"type": "event", "t": row.t_close, "action": "close",
                                           "event": dict(edict, t=row.t_close)}))

    # Status messages for each whole second in [t0, t1], with the latest
    # snapshot per source carried forward.
    #
    # snapshot_rows[src] is ORDER BY t (EpochStore.query guarantees this), and
    # the seconds we iterate are strictly increasing, so a single
    # forward-advancing index per src -- carried across seconds rather than
    # rescanned from scratch each second -- is enough to find "latest row
    # with t <= sec": each row is visited at most once across the whole loop,
    # giving O(seconds + epochs) instead of the O(seconds * epochs) a fresh
    # per-second list comprehension would cost.
    idx = {src: 0 for src in _SRC_ALL}
    last: dict[str, object] = {src: None for src in _SRC_ALL}
    for sec in range(math.ceil(t0), math.floor(t1) + 1):
        for src in _SRC_ALL:
            rows = snapshot_rows[src]
            i = idx[src]
            n = len(rows)
            while i < n and rows[i].t <= sec:
                last[src] = rows[i]
                i += 1
            idx[src] = i

        sol_row = last["rtkrcv"]
        sol_dict = None
        if sol_row is not None:
            # Exact 11-key contract shared with the realtime status.sol dict
            # (main.py's _diagnosis_tick) -- not the full Epoch asdict, which
            # would leak src/heading/speed/sats_json that realtime never
            # includes for the sol slot.
            sol_dict = {
                "t": sol_row.t, "q": sol_row.q, "sats": sol_row.sats,
                "age": sol_row.age, "ratio": sol_row.ratio,
                "lat": sol_row.lat, "lon": sol_row.lon, "alt": sol_row.alt,
                "sdn": sol_row.sdn, "sde": sol_row.sde, "sdu": sol_row.sdu,
            }
        can_dict = dataclasses.asdict(last["can"]) if last["can"] is not None else None
        gpchc_dict = dataclasses.asdict(last["gpchc"]) if last["gpchc"] is not None else None

        timeline.append((float(sec), {
            "type": "status", "t": float(sec),
            "verdict": {"level": "info", "code": "replay", "message": "回放"},
            "sol": sol_dict, "can": can_dict, "gpchc": gpchc_dict,
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
