"""Pure report statistics over stored epochs/events (spec §6)."""
from __future__ import annotations

import math

from rtk_monitor.storage.epochs import EpochStore
from rtk_monitor.storage.events import EventStore


def _fix_ratio(rows, fixed_q: int) -> float | None:
    if not rows:
        return None
    return sum(1 for e in rows if e.q == fixed_q) / len(rows)


def _horiz_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle horizontal distance in metres (haversine)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def compute_report(epochs: EpochStore, events: EventStore, t0: float, t1: float,
                   control_points=(), abs_ref_radius_m: float = 3.0) -> dict:
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
    for r in events.query(since=0.0):
        if r.etype != "diagnosis":
            # The events table also stores link/crash rows (etype
            # corr_link/web/rtkrcv/...); the report only summarizes
            # diagnosis outcomes.
            continue
        still_open = r.t_close is None
        if r.t > t1 or ((not still_open) and r.t_close < t0):
            continue
        evs.append({"code": r.code, "level": r.level, "t": r.t, "t_close": r.t_close,
                    "duration_s": (r.t_close - r.t) if r.t_close is not None else None,
                    "message": r.detail})
    hist = [h for h in epochs.base_history() if t0 <= h[0] <= t1]
    base_max = None
    if hist:
        x0, y0, z0 = hist[0][1:]
        base_max = max(math.dist((x0, y0, z0), h[1:]) for h in hist)

    # Absolute-baseline verification (§6 必含项): for each rtkrcv epoch that was
    # at (within abs_ref_radius_m of) a surveyed control point, the deviation
    # from that point's known coordinate — the last-resort curve that exposes a
    # whole-mine shift the other stats stay green through.
    abs_ref = []
    for e in rtk:
        if e.lat is None:
            continue
        for cp in control_points:
            dev = _horiz_m(e.lat, e.lon, cp.lat, cp.lon)
            if dev <= abs_ref_radius_m:
                abs_ref.append({"t": e.t, "cp": cp.name, "dev_m": dev})
    abs_ref_max = max((r["dev_m"] for r in abs_ref), default=None)

    return {"fix_ratio": _fix_ratio(main_rows, fixed_q), "hourly": hourly,
            "events": sorted(evs, key=lambda e: e["t"]),
            "base_max_offset_m": base_max,
            "abs_ref": abs_ref, "abs_ref_max_m": abs_ref_max,
            "epoch_counts": {"rtkrcv": len(rtk), "can": len(can), "gpchc": len(gpchc)}}
