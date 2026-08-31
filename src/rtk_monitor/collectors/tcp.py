"""TCP stream collector: connect-or-listen, deliver raw chunks, reconnect forever.

The collector performs no parsing — its only jobs are delivering bytes with a
host timestamp and reporting link state transitions.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable

OnData = Callable[[bytes, float], None]
OnEvent = Callable[[str, str, str], None]


class TcpCollector:
    def __init__(self, name: str, host: str, port: int,
                 on_data: OnData, on_event: OnEvent, listen: bool = False,
                 initial_backoff: float = 1.0, max_backoff: float = 30.0) -> None:
        self._name = name
        self._host = host
        self._port = port
        self._on_data = on_data
        self._on_event = on_event
        self._listen = listen
        self._initial = initial_backoff
        self._max = max_backoff
        self.bound_port: int | None = None

    async def run(self) -> None:
        if self._listen:
            await self._run_server()
        else:
            await self._run_client()

    async def _pump(self, reader: asyncio.StreamReader) -> None:
        self._on_event(self._name, "connected", "")
        while True:
            data = await reader.read(4096)
            if not data:
                break
            self._on_data(data, time.time())

    async def _run_client(self) -> None:
        backoff = self._initial
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(self._host, self._port)
                backoff = self._initial
                await self._pump(reader)
            except OSError:
                pass
            finally:
                if writer is not None:
                    writer.close()
            self._on_event(self._name, "disconnected", f"retry in {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._max)

    async def _run_server(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                await self._pump(reader)
            finally:
                self._on_event(self._name, "disconnected", "peer closed")
                writer.close()

        server = await asyncio.start_server(handler, self._host, self._port)
        self.bound_port = server.sockets[0].getsockname()[1]
        async with server:
            await server.serve_forever()
