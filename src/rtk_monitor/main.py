"""Wire config -> collectors -> writers/reserver/events. Entry point of Plan 1/2.

CAN channel naming: "can0" opens SocketCAN; "virtual:<name>" opens a python-can
virtual bus (tests / replay without hardware).
"""
from __future__ import annotations

import asyncio
import logging
import math
import socket
import sys
import time
from typing import Callable, Coroutine

import can

from rtk_monitor.config import Config, load_config
from rtk_monitor.collectors.can import CanCollector
from rtk_monitor.collectors.reserve import LocalReserver
from rtk_monitor.collectors.tcp import TcpCollector
from rtk_monitor.diagnosis.base_station import BaseStationMonitor
from rtk_monitor.diagnosis.events import EventMachine
from rtk_monitor.diagnosis.rules import DiagnosisInput, diagnose
from rtk_monitor.parsers.cgi610_can import Cgi610Assembler
from rtk_monitor.parsers.gpchc import LineFramer, parse_gpchc
from rtk_monitor.parsers.rtcm import RtcmFramer, parse_1005
from rtk_monitor.parsers.rtksol import parse_llh_solution
from rtk_monitor.parsers.rtkstat import SlipWindow
from rtk_monitor.publisher import UdpPublisher
from rtk_monitor.solver.rtkrcv import RtkrcvManager
from rtk_monitor.storage.canlog import CandumpWriter
from rtk_monitor.storage.cleanup import cleanup_logs
from rtk_monitor.storage.epochs import Epoch, EpochStore
from rtk_monitor.storage.events import EventStore
from rtk_monitor.storage.rawlog import RawLogWriter

_CLEANUP_INTERVAL_S = 3600.0
_SUPERVISE_RESTART_S = 5.0
_DIAGNOSIS_INTERVAL_S = 1.0

_logger = logging.getLogger(__name__)


def _horiz_dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular-projection horizontal distance (good enough at this scale)."""
    r = 6378137.0
    x = math.radians(lon2 - lon1) * r * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1) * r
    return math.hypot(x, y)


def _pick_free_port() -> int:
    """Bind to port 0 to let the OS choose a free TCP port, then release it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


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
        self._gpchc_framer = LineFramer()
        self._rtksol_framer = LineFramer()
        self._can_assembler = Cgi610Assembler()

        # Plan 2: epoch store, diagnosis engine, base-station monitor, publisher.
        self.epochs = EpochStore(cfg.db_path)
        self.base_monitor = BaseStationMonitor(self.epochs)
        self.publisher: UdpPublisher | None = (
            UdpPublisher(cfg.publish.host, cfg.publish.port) if cfg.publish.enabled else None)
        self.event_machine = EventMachine(
            self.events, close_hysteresis_s=cfg.diagnosis.close_hysteresis_s,
            on_transition=self._on_diagnosis_transition)

        # Diagnosis-loop state.
        self._corr_last_t: float | None = None
        self._base_offset: float | None = None
        self._sol = None
        self._sol_t: float | None = None
        self._div_since: float | None = None
        self._slips = SlipWindow()
        self._last_epoch_write: dict[str, int] = {}

        self._sol_collector = TcpCollector(
            "gnss_solution_link", cfg.gnss_solution.host, cfg.gnss_solution.port,
            self._on_sol, self._on_event, listen=cfg.gnss_solution.listen)
        self._collectors = [
            TcpCollector("corrections_link", cfg.corrections.host, cfg.corrections.port,
                         self._on_corr, self._on_event, listen=cfg.corrections.listen),
            TcpCollector("raw_obs_link", cfg.raw_obs.host, cfg.raw_obs.port,
                         self._on_obs, self._on_event, listen=cfg.raw_obs.listen),
            self._sol_collector,
        ]
        channel = cfg.can_channel
        bus_factory: Callable[[], can.BusABC] | None = None
        if channel.startswith("virtual:"):
            name = channel.split(":", 1)[1]
            self._bus = can.Bus(interface="virtual", channel=name)
            # Name the candump log stream so it matches the "can*_*.log" glob
            # used by tools and tests (e.g. virtual:e2e -> "can_e2e").
            log_name = "can_" + name
        else:
            self._bus = can.Bus(interface="socketcan", channel=channel)
            log_name = channel
            # Real hardware: wire the reopen watchdog so a wedged SocketCAN
            # link (e.g. after a controller reset) gets a fresh bus instead
            # of leaving the collector reading from a dead one forever.
            bus_factory = lambda: can.Bus(interface="socketcan", channel=channel)
        self._can_log = CandumpWriter(cfg.data_root, log_name)
        self._can_collector = CanCollector(self._bus, self._on_can, self._on_event,
                                            bus_factory=bus_factory)

        # rtkrcv solver: only wired when a binary path is configured. The
        # corr/obs ports it dials come from the reserver's bound ports, which
        # aren't known until the reservers start (Task-4 auto-bind: config
        # port 0 means "pick a free port"), so RtkrcvManager itself is built
        # in run_forever(). The sol port, however, is resolved here in
        # __init__ per the binding note: it must be known (and stable) before
        # run_forever so sol_collector_port()-style callers can rely on it.
        self._rtkrcv_manager: RtkrcvManager | None = None
        self._rtkrcv_sol_collector: TcpCollector | None = None
        self._sol_port: int | None = None
        if cfg.rtkrcv.binary:
            self._sol_port = cfg.rtkrcv.sol_port or _pick_free_port()
            self._rtkrcv_sol_collector = TcpCollector(
                "rtkrcv_sol", "127.0.0.1", self._sol_port,
                self._on_rtksol, self._on_event)

    # --- stream callbacks: log first, then fan out -------------------------
    # Every callback below is invoked synchronously from inside a collector's
    # pump loop. None of them may let an exception escape -- a storage error
    # (e.g. sqlite3.OperationalError, a full disk) must never propagate back
    # into a collector and take down its route (spec: "collection never
    # stops"). Append and broadcast are guarded in separate try/except blocks
    # so a failed append does not skip the broadcast (spec Sec3.3).
    def _on_corr(self, data: bytes, t: float) -> None:
        # Any corrections traffic (not just 1005/1006) counts as "link alive"
        # for the diagnosis loop's outage rule.
        self._corr_last_t = time.time()
        try:
            for msg in self._corr_framer.feed(data):
                try:
                    self._corr_log.append(msg.raw, msg.msg_type)
                except Exception:
                    _logger.exception("corr rawlog append failed")
                if msg.msg_type in (1005, 1006):
                    try:
                        x, y, z = parse_1005(msg.payload)
                        self._base_offset = self.base_monitor.feed(time.time(), x, y, z)
                    except Exception:
                        _logger.exception("base station update failed")
        except Exception:
            _logger.exception("corr framer feed failed")
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
        # Route 3: GPCHC ASCII sentences from the CGI-610's TCP interface.
        try:
            self._sol_log.append(data)
        except Exception:
            _logger.exception("sol rawlog append failed")
        try:
            for line in self._gpchc_framer.feed(data):
                e = parse_gpchc(line)
                if e is None:
                    continue
                sec = int(t)
                if self._last_epoch_write.get("gpchc") == sec:
                    continue
                self._last_epoch_write["gpchc"] = sec
                self.epochs.add(Epoch(
                    t=t, src="gpchc", q=e.sat_status, sats=e.nsv1, age=e.diff_age,
                    lat=e.lat, lon=e.lon, alt=e.alt, heading=e.heading, speed=e.speed))
        except Exception:
            _logger.exception("gpchc epoch decode failed")

    def _on_rtksol(self, data: bytes, t: float) -> None:
        # rtkrcv's own llh-format solution stream (only wired when enabled).
        try:
            for line in self._rtksol_framer.feed(data):
                sol = parse_llh_solution(line)
                if sol is None:
                    continue
                self._sol = sol
                self._sol_t = t
                # rtkrcv emits at the solver's full solution rate (up to
                # ~5-10Hz); decimate epoch storage to 1Hz like the other
                # sources (gpchc/can) to avoid unbounded DB growth over a
                # multi-week unattended run. publish_fix stays per-solution.
                sec = int(t)
                if self._last_epoch_write.get("rtkrcv") != sec:
                    self._last_epoch_write["rtkrcv"] = sec
                    try:
                        self.epochs.add(Epoch(
                            t=t, src="rtkrcv", q=sol.q, sats=sol.ns, age=sol.age,
                            lat=sol.lat, lon=sol.lon, alt=sol.alt,
                            sde=sol.sde, sdn=sol.sdn, sdu=sol.sdu, ratio=sol.ratio))
                    except Exception:
                        _logger.exception("rtkrcv epoch store failed")
                if self.publisher is not None:
                    try:
                        self.publisher.publish_fix(sol, heading=self._latest_heading())
                    except Exception:
                        _logger.exception("publish_fix failed")
        except Exception:
            _logger.exception("rtksol decode failed")

    def _latest_heading(self) -> float | None:
        """Most recent heading from either the gpchc or can epoch source."""
        g = self.epochs.latest("gpchc")
        c = self.epochs.latest("can")
        if g is None:
            return c.heading if c is not None else None
        if c is None:
            return g.heading
        return g.heading if g.t >= c.t else c.heading

    def _on_can(self, can_id: int, data: bytes, t: float) -> None:
        try:
            self._can_log.append(can_id, data, t)
        except Exception:
            _logger.exception("can log append failed")
        try:
            cyc = self._can_assembler.feed(can_id, data, t)
            if cyc is not None:
                sec = int(cyc.host_time)
                if self._last_epoch_write.get("can") != sec:
                    self._last_epoch_write["can"] = sec
                    self.epochs.add(Epoch(
                        t=cyc.host_time, src="can", q=cyc.sat_status, sats=cyc.sats_used,
                        age=cyc.diff_age, lat=cyc.lat, lon=cyc.lon, alt=cyc.alt,
                        sde=cyc.pos_sigma[0], sdn=cyc.pos_sigma[1], sdu=cyc.pos_sigma[2],
                        heading=cyc.heading, speed=cyc.vel[3]))
        except Exception:
            _logger.exception("can epoch decode failed")

    def _on_event(self, name: str, state: str, detail: str) -> None:
        try:
            self.events.record(time.time(), name, state, detail)
        except Exception:
            _logger.exception("event record failed: %s %s %r", name, state, detail)

    def _on_diagnosis_transition(self, kind: str, verdict, t: float) -> None:
        if self.publisher is None:
            return
        try:
            self.publisher.publish_event(kind, verdict, t)
        except Exception:
            _logger.exception("publish_event failed")

    def sol_collector_port(self) -> int | None:
        """Route-3 (GPCHC) listen port. Used by tests and Plan 3's UI."""
        return self._sol_collector.bound_port

    # --- lifecycle ---------------------------------------------------------
    async def run_forever(self) -> None:
        await self.corr_reserver.start(self.cfg.reserve_corrections_port)
        await self.obs_reserver.start(self.cfg.reserve_raw_obs_port)
        if self.cfg.rtkrcv.binary:
            # corr/obs ports dial the reservers' fan-out (bound ports are only
            # known now, after reserve_*_port=0 auto-bind has resolved).
            self._rtkrcv_manager = RtkrcvManager(
                self.cfg.rtkrcv.binary, run_dir=self.cfg.data_root / "rtkrcv",
                corr_port=self.corr_reserver.bound_port,
                obs_port=self.obs_reserver.bound_port,
                sol_port=self._sol_port,
                extra_args=self.cfg.rtkrcv.extra_args, on_event=self._on_event)
        if self.publisher is not None:
            await self.publisher.start()
        supervised: list[tuple[str, Callable[[], Coroutine]]] = [
            (c.name, c.run) for c in self._collectors
        ]
        supervised.append(("can_collector", self._can_collector.run))
        supervised.append(("diagnosis_loop", self._diagnosis_loop))
        if self._rtkrcv_manager is not None:
            supervised.append(("rtkrcv", self._rtkrcv_manager.run))
        if self._rtkrcv_sol_collector is not None:
            supervised.append((self._rtkrcv_sol_collector.name, self._rtkrcv_sol_collector.run))
        tasks = [asyncio.create_task(self._supervise(name, factory))
                 for name, factory in supervised]
        tasks.append(asyncio.create_task(self._cleanup_loop()))
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise

    async def _diagnosis_loop(self) -> None:
        while True:
            await asyncio.sleep(_DIAGNOSIS_INTERVAL_S)
            try:
                self._diagnosis_tick()
            except Exception:
                # A transient failure (e.g. a bad epoch row) must not kill
                # the 1Hz cadence -- log and try again next tick.
                _logger.exception("diagnosis tick failed")

    def _diagnosis_tick(self) -> None:
        now = time.time()
        # A frozen solver output (rtkrcv stopped emitting) must not be treated
        # as a live solution forever -- gate it on recency so the rule chain
        # degrades to the "no_solution" path instead of reporting a stale fix
        # at a stale position indefinitely.
        sol = (self._sol if (self._sol_t is not None
                              and now - self._sol_t < self.cfg.diagnosis.sol_stale_s)
               else None)
        div_m = None
        can_e = self.epochs.latest("can")
        if can_e is not None and now - can_e.t > self.cfg.diagnosis.sol_stale_s:
            # Same freshness gate as the solver output: latest("can") returns
            # the newest row regardless of age, so after the CAN link dies a
            # minutes-old epoch would keep feeding the corr-age fallback
            # (rule 1 blaming the corrections link for a dead CAN feed) and
            # the event lat/lon fallback (pinning events to a stale position).
            can_e = None
        if (sol is not None and can_e is not None and can_e.lat is not None
                and abs((self._sol_t or 0) - can_e.t) < 2.0):
            div_m = _horiz_dist_m(sol.lat, sol.lon, can_e.lat, can_e.lon)
            sigma = max(1e-3, (sol.sdn ** 2 + sol.sde ** 2) ** 0.5)
            if div_m > self.cfg.diagnosis.divergence_sigma * sigma:
                self._div_since = self._div_since or now
            else:
                self._div_since = None
        else:
            # No fresh sol/CAN pair to compare -- any previously-held
            # divergence timer is stale and must not survive to fire rule 7
            # instantly once data returns.
            self._div_since = None
        inp = DiagnosisInput(
            now=now, corr_last_t=self._corr_last_t,
            corr_age=sol.age if sol else
                     (can_e.age if can_e else None),
            base_offset_m=self._base_offset,
            sol=sol, sol_t=self._sol_t,
            sats=[], slip_count_30s=self._slips.count(now),
            divergence_m=div_m, divergence_since=self._div_since,
            solver_enabled=(self.cfg.rtkrcv.binary != ""))
        v = diagnose(inp, self.cfg.diagnosis)
        lat = sol.lat if sol else (can_e.lat if can_e else None)
        lon = sol.lon if sol else (can_e.lon if can_e else None)
        self.event_machine.update(now, v, lat, lon)

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
                cutoff = time.time() - self.cfg.db_retention_days * 86400.0
                self.epochs.prune(cutoff)
                self.events.prune(cutoff)
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
        if self.publisher is not None:
            await self.publisher.stop()
        # Note: self.events/self.epochs are intentionally left open here. App
        # exposes both as the diagnostic/query surface for callers (and for
        # Plan 2's diagnosis engine host), so they must stay queryable after
        # shutdown() returns. Callers that want to fully release the sqlite
        # handles can call .close() on them once done.


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
