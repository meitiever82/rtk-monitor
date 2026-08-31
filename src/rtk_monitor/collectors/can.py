"""SocketCAN (or any python-can bus) collector."""
from __future__ import annotations

import asyncio
import time
from typing import Callable

import can

OnFrame = Callable[[int, bytes, float], None]
OnEvent = Callable[[str, str, str], None]


class CanCollector:
    def __init__(self, bus: can.BusABC, on_frame: OnFrame,
                 on_event: OnEvent | None = None, data_timeout: float = 2.0) -> None:
        self._bus = bus
        self._on_frame = on_frame
        self._on_event = on_event
        self._data_timeout = data_timeout

    def _emit(self, name: str, state: str, detail: str) -> None:
        if self._on_event is not None:
            self._on_event(name, state, detail)

    async def run(self) -> None:
        reader = can.AsyncBufferedReader()
        notifier = can.Notifier(self._bus, [reader], loop=asyncio.get_running_loop())
        # Unknown until either a frame arrives or the watchdog times out; only
        # emit "connected" the first time we actually see traffic, and
        # "disconnected" once per outage (not once per poll).
        seen_frame = False
        disconnected = False
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(reader.get_message(),
                                                  timeout=self._data_timeout)
                except asyncio.TimeoutError:
                    if not disconnected:
                        disconnected = True
                        self._emit("can_link", "disconnected",
                                   f"no frames for {self._data_timeout:.0f}s")
                    continue
                if not seen_frame or disconnected:
                    seen_frame = True
                    disconnected = False
                    self._emit("can_link", "connected", "")
                self._on_frame(msg.arbitration_id, bytes(msg.data),
                               msg.timestamp or time.time())
        finally:
            notifier.stop()
