"""candump -L compatible hourly log, so existing decode scripts keep working."""
from __future__ import annotations

import time
from pathlib import Path

from rtk_monitor.storage.rawlog import RawLogWriter


class CandumpWriter:
    def __init__(self, root: Path, channel: str, clock=time.time) -> None:
        self._channel = channel
        self._raw = RawLogWriter(root, channel, ext="log", clock=clock)

    def append(self, can_id: int, data: bytes, t: float) -> None:
        line = f"({t:.6f}) {self._channel} {can_id:03X}#{data.hex().upper()}\n"
        self._raw.append(line.encode("ascii"))

    def close(self) -> None:
        self._raw.close()
