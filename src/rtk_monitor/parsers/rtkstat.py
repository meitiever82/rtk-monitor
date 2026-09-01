"""Parse rtkrcv solution-status $SAT lines; track cycle-slip counts in a window."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SatStat:
    tow: float
    sat: str
    az: float
    el: float
    resp: float       # pseudorange residual (m)
    snr: float        # dBHz
    valid: bool
    slipc: int
    rejc: int


def parse_sat_line(line: str) -> SatStat | None:
    if not line.startswith("$SAT,"):
        return None
    p = line.strip().split(",")
    if len(p) < 17:
        return None
    try:
        return SatStat(tow=float(p[2]), sat=p[3], az=float(p[5]), el=float(p[6]),
                       resp=float(p[7]), snr=float(p[10]), valid=p[9] == "1",
                       slipc=int(p[15]), rejc=int(p[16]))
    except ValueError:
        return None


class SlipWindow:
    """Count cycle-slip increments across all satellites within a sliding window."""

    def __init__(self, window_s: float = 30.0) -> None:
        self._window = window_s
        self._last: dict[str, int] = {}
        self._hits: list[tuple[float, int]] = []   # (t, delta)

    def feed(self, t: float, sat: str, slipc: int) -> None:
        prev = self._last.get(sat)
        self._last[sat] = slipc
        if prev is not None and slipc > prev:
            self._hits.append((t, slipc - prev))

    def count(self, now: float) -> int:
        cutoff = now - self._window
        self._hits = [(t, d) for t, d in self._hits if t >= cutoff]
        return sum(d for _, d in self._hits)
