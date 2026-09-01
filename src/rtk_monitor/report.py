"""Pure report statistics over stored epochs/events (spec §6)."""
from __future__ import annotations

import math

from rtk_monitor.storage.epochs import EpochStore
from rtk_monitor.storage.events import EventStore


def _fix_ratio(rows, fixed_q: int) -> float | None:
    if not rows:
        return None
    return sum(1 for e in rows if e.q == fixed_q) / len(rows)


def compute_report(epochs: EpochStore, events: EventStore, t0: float, t1: float) -> dict:
    rtk = epochs.query("rtkrcv", t0, t1)
    can = epochs.query("can", t0, t1)
    gpchc = epochs.query("gpchc", t0, t1)
    main_rows, fixed_q = (rtk, 1) if rtk else (can, 4)
    hourly = []
    if main_rows:
        h0, h1 = int(t0 // 3600), int(t1 // 3600)
        for h in range(h0, h1 + 1):
            rows = [e for e in main_rows if h * 3600 <= e.t < (h + 1) * 3600]
            hourly.append({"hour": h, "epochs": len(rows),
                           "fix_ratio": _fix_ratio(rows, fixed_q)})
    evs = []
    for r in events.query(since=t0):
        if r.t > t1:
            continue
        evs.append({"code": r.code, "level": r.level, "t": r.t, "t_close": r.t_close,
                    "duration_s": (r.t_close - r.t) if r.t_close else None,
                    "message": r.detail})
    hist = [h for h in epochs.base_history() if t0 <= h[0] <= t1]
    base_max = None
    if hist:
        x0, y0, z0 = hist[0][1:]
        base_max = max(math.dist((x0, y0, z0), h[1:]) for h in hist)
    return {"fix_ratio": _fix_ratio(main_rows, fixed_q), "hourly": hourly,
            "events": sorted(evs, key=lambda e: e["t"]),
            "base_max_offset_m": base_max,
            "epoch_counts": {"rtkrcv": len(rtk), "can": len(can), "gpchc": len(gpchc)}}
