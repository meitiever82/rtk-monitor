"""Wire config -> collectors -> writers/reserver/events. Entry point of Plan 1.

CAN channel naming: "can0" opens SocketCAN; "virtual:<name>" opens a python-can
virtual bus (tests / replay without hardware).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Callable, Coroutine

import can

from rtk_monitor.config import Config, load_config
from rtk_monitor.collectors.can import CanCollector
from rtk_monitor.collectors.reserve import LocalReserver
from rtk_monitor.collectors.tcp import TcpCollector
from rtk_monitor.parsers.rtcm import RtcmFramer
from rtk_monitor.storage.canlog import CandumpWriter
from rtk_monitor.storage.cleanup import cleanup_logs
from rtk_monitor.storage.events import EventStore
from rtk_monitor.storage.rawlog import RawLogWriter

_CLEANUP_INTERVAL_S = 3600.0
_SUPERVISE_RESTART_S = 5.0

_logger = logging.getLogger(__name__)


class App:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        cfg.data_root.mkdir(parents=True, exist_ok=True)
        self.events = EventStore(cfg.db_path)
        self.corr_reserver = LocalReserver()
        self.obs_reserver = LocalReserver()

        self._corr_log = RawLogWriter(cfg.data_root, "corr", ext="rtcm3")
        self._obs_log = RawLogWriter(cfg.data_root, "obs", ext="rtcm3")
        self._sol_log = RawLogWriter(cfg.data_root, "sol", ext="txt")
        self._corr_framer = RtcmFramer()
        self._obs_framer = RtcmFramer()

        self._collectors = [
            TcpCollector("corrections_link", cfg.corrections.host, cfg.corrections.port,
                         self._on_corr, self._on_event, listen=cfg.corrections.listen),
            TcpCollector("raw_obs_link", cfg.raw_obs.host, cfg.raw_obs.port,
                         self._on_obs, self._on_event, listen=cfg.raw_obs.listen),
            TcpCollector("gnss_solution_link", cfg.gnss_solution.host, cfg.gnss_solution.port,
                         self._on_sol, self._on_event, listen=cfg.gnss_solution.listen),
        ]
        channel = cfg.can_channel
        if channel.startswith("virtual:"):
            name = channel.split(":", 1)[1]
            self._bus = can.Bus(interface="virtual", channel=name)
            # Name the candump log stream so it matches the "can*_*.log" glob
            # used by tools and tests (e.g. virtual:e2e -> "can_e2e").
            log_name = "can_" + name
        else:
            self._bus = can.Bus(interface="socketcan", channel=channel)
            log_name = channel
        self._can_log = CandumpWriter(cfg.data_root, log_name)
        self._can_collector = CanCollector(self._bus, self._on_can, self._on_event)

    # --- stream callbacks: log first, then fan out -------------------------
    # Every callback below is invoked synchronously from inside a collector's
    # pump loop. None of them may let an exception escape -- a storage error
    # (e.g. sqlite3.OperationalError, a full disk) must never propagate back
    # into a collector and take down its route (spec: "collection never
    # stops"). Append and broadcast are guarded in separate try/except blocks
    # so a failed append does not skip the broadcast (spec Sec3.3).
    def _on_corr(self, data: bytes, t: float) -> None:
        try:
            for msg in self._corr_framer.feed(data):
                self._corr_log.append(msg.raw, msg.msg_type)
        except Exception:
            _logger.exception("corr rawlog append failed")
        try:
            self.corr_reserver.broadcast(data)
        except Exception:
            _logger.exception("corr broadcast failed")

    def _on_obs(self, data: bytes, t: float) -> None:
        try:
            for msg in self._obs_framer.feed(data):
                self._obs_log.append(msg.raw, msg.msg_type)
        except Exception:
            _logger.exception("obs rawlog append failed")
        try:
            self.obs_reserver.broadcast(data)
        except Exception:
            _logger.exception("obs broadcast failed")

    def _on_sol(self, data: bytes, t: float) -> None:
        try:
            self._sol_log.append(data)
        except Exception:
            _logger.exception("sol rawlog append failed")

    def _on_can(self, can_id: int, data: bytes, t: float) -> None:
        try:
            self._can_log.append(can_id, data, t)
        except Exception:
            _logger.exception("can log append failed")

    def _on_event(self, name: str, state: str, detail: str) -> None:
        try:
            self.events.record(time.time(), name, state, detail)
        except Exception:
            _logger.exception("event record failed: %s %s %r", name, state, detail)

    # --- lifecycle ---------------------------------------------------------
    async def run_forever(self) -> None:
        await self.corr_reserver.start(self.cfg.reserve_corrections_port)
        await self.obs_reserver.start(self.cfg.reserve_raw_obs_port)
        supervised: list[tuple[str, Callable[[], Coroutine]]] = [
            (c.name, c.run) for c in self._collectors
        ]
        supervised.append(("can_collector", self._can_collector.run))
        tasks = [asyncio.create_task(self._supervise(name, factory))
                 for name, factory in supervised]
        tasks.append(asyncio.create_task(self._cleanup_loop()))
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise

    async def _supervise(self, name: str, coro_factory: Callable[[], Coroutine]) -> None:
        """Run coro_factory() forever, restarting it on any non-cancellation
        exception. A single misbehaving route (a collector task dying for an
        unforeseen reason) must never unwind the other routes via gather."""
        while True:
            try:
                await coro_factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception("%s crashed; restarting in %.0fs", name,
                                   _SUPERVISE_RESTART_S)
                try:
                    self._on_event(name, "crashed", "restarting")
                except Exception:
                    _logger.exception("failed to record crash event for %s", name)
                await asyncio.sleep(_SUPERVISE_RESTART_S)

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                cleanup_logs(self.cfg.data_root, self.cfg.retention_days,
                             self.cfg.disk_watermark_pct)
            except Exception:
                # A transient filesystem error must not kill the hourly loop.
                _logger.exception("cleanup failed")
            await asyncio.sleep(_CLEANUP_INTERVAL_S)

    async def shutdown(self) -> None:
        for w in (self._corr_log, self._obs_log, self._sol_log, self._can_log):
            w.close()
        await self.corr_reserver.stop()
        await self.obs_reserver.stop()
        self._bus.shutdown()
        # Note: self.events is intentionally left open here. App exposes
        # `events` as the diagnostic/query surface for callers (and for
        # Plan 2's diagnosis engine host), so it must stay queryable after
        # shutdown() returns. Callers that want to fully release the sqlite
        # handle can call self.events.close() themselves once done.


def build_app(cfg: Config) -> App:
    return App(cfg)


def main() -> None:
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    app = build_app(cfg)
    try:
        asyncio.run(app.run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
