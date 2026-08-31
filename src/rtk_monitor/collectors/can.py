"""SocketCAN (or any python-can bus) collector."""
from __future__ import annotations

import asyncio
import time
from typing import Callable

import can

OnFrame = Callable[[int, bytes, float], None]


class CanCollector:
    def __init__(self, bus: can.BusABC, on_frame: OnFrame) -> None:
        self._bus = bus
        self._on_frame = on_frame

    async def run(self) -> None:
        reader = can.AsyncBufferedReader()
        notifier = can.Notifier(self._bus, [reader], loop=asyncio.get_running_loop())
        try:
            while True:
                msg = await reader.get_message()
                self._on_frame(msg.arbitration_id, bytes(msg.data),
                               msg.timestamp or time.time())
        finally:
            notifier.stop()
