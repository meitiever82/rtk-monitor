"""FastAPI service: REST, WebSocket (live + replay), report page, tiles, static UI."""
from __future__ import annotations

import asyncio
import dataclasses
import html
import logging
import math
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from rtk_monitor.replay import replay_messages
from rtk_monitor.report import compute_report

_logger = logging.getLogger(__name__)

# {"cmd":"replay","t1":9e15} used to reach replay_messages unvalidated and
# build one status entry per second over the whole [t0, t1] range -- billions
# of entries, synchronously, on the event loop. Clamp the window itself
# (independent of anything replay.py does) so a malicious/buggy client can
# never request more than this much real time.
_MAX_REPLAY_WINDOW_S = 48 * 3600.0


def _web_dir(app) -> Path:
    cfg = getattr(app, "cfg", None)
    if cfg is not None and getattr(cfg.web, "static_dir", ""):
        return Path(cfg.web.static_dir)
    return Path(__file__).resolve().parents[2] / "web"


def _validate_replay_cmd(cmd: dict) -> tuple[float, float, float] | None:
    """Return a (t0, t1, speed) triple clamped to <=48h, or None if `cmd` is
    not a well-formed replay command (missing/non-numeric t0/t1, NaN/inf,
    t1<=t0, or a non-finite/non-positive speed)."""
    try:
        t0 = float(cmd["t0"])
        t1 = float(cmd["t1"])
        speed = float(cmd.get("speed", 1.0))
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(t0) and math.isfinite(t1) and math.isfinite(speed)):
        return None
    if not (t1 > t0 and speed > 0):
        return None
    t0 = max(t0, t1 - _MAX_REPLAY_WINDOW_S)
    return t0, t1, speed


def create_api(app) -> FastAPI:            # app: rtk_monitor.main.App (duck-typed)
    api = FastAPI(title="rtk-monitor")

    # Route handlers below are `async def` (not plain `def`) so FastAPI runs
    # them directly on the calling event-loop thread instead of dispatching
    # them to Starlette's worker threadpool. app.epochs/app.events wrap
    # sqlite3 connections; keeping all access on one thread avoids relying
    # solely on check_same_thread=False for correctness and matches how the
    # rest of App already touches these stores from its single event loop.
    @api.get("/api/status")
    async def status():
        return app.last_status or {"type": "status", "t": None}

    @api.get("/api/events")
    async def events(since: float = 0.0):
        return [dataclasses.asdict(r) for r in app.events.query(since=since)]

    @api.get("/api/epochs")
    async def epochs(src: str, t0: float, t1: float, limit: int = 3600):
        # query(...)[-limit:] used to materialize the full [t0, t1] range in
        # Python just to discard everything but the tail; query_last pushes
        # the "newest N" selection into SQL instead.
        clamped_limit = max(1, min(limit, 50000))
        return [dataclasses.asdict(e) for e in app.epochs.query_last(src, t0, t1, clamped_limit)]

    @api.get("/api/base_history")
    async def base_history():
        return app.epochs.base_history()

    @api.post("/api/base_reset")
    async def base_reset():
        hist = app.epochs.base_history()
        if not hist:
            raise HTTPException(409, "no base station history")
        t, x, y, z = hist[-1]
        app.base_monitor.reset(t, x, y, z)
        return {"ok": True, "xyz": [x, y, z]}

    @api.get("/api/report")
    async def report_json(t0: float, t1: float):
        return compute_report(app.epochs, app.events, t0, t1)

    @api.get("/report", response_class=HTMLResponse)
    async def report_html(t0: float, t1: float):
        r = compute_report(app.epochs, app.events, t0, t1)

        def pct(v):
            return "-" if v is None else f"{v:.1%}"

        rows = "".join(
            f"<tr><td>{html.escape(str(h['hour']))}</td><td>{h['epochs']}</td><td>{pct(h['fix_ratio'])}</td></tr>"
            for h in r["hourly"])
        evs = "".join(f"<tr><td>{html.escape(e['code'] or '')}</td><td>{html.escape(e['level'] or '')}</td>"
                      f"<td>{'-' if e['duration_s'] is None else e['duration_s']}</td>"
                      f"<td>{html.escape(e['message'] or '')}</td></tr>"
                      for e in r["events"])
        fr = "-" if r["fix_ratio"] is None else f"{r['fix_ratio']:.1%}"
        return f"""<html><meta charset="utf-8"><body style="font-family:sans-serif;max-width:800px;margin:2em auto">
<h1>RTK 定位报告</h1><p>固定解可用率：<b>{fr}</b>　基站最大偏移：{r['base_max_offset_m'] or '-'} m</p>
<h2>分小时统计</h2><table border=1 cellpadding=4><tr><th>小时</th><th>历元数</th><th>固定率</th></tr>{rows}</table>
<h2>事件（{len(r['events'])}）</h2><table border=1 cellpadding=4><tr><th>类型</th><th>级别</th><th>时长(s)</th><th>结论</th></tr>{evs}</table>
</body></html>"""

    @api.get("/tiles/{z}/{x}/{y}.png")
    async def tile(z: int, x: int, y: int):
        if not (0 <= z <= 25):
            raise HTTPException(404, "invalid zoom")
        if app.tile_store is None:
            raise HTTPException(404, "no tiles configured")
        data = app.tile_store.get(z, x, y)
        if data is None:
            raise HTTPException(404, "tile not found")
        return Response(data, media_type="image/png")

    @api.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q = app.broadcaster.subscribe()
        replay_task: asyncio.Task | None = None

        def _log_task_exception(t: asyncio.Task) -> None:
            # WS task exceptions otherwise vanish silently: asyncio only
            # reports an unretrieved exception via its default handler once
            # the task is garbage-collected (if ever), and neither live()
            # nor run_replay() is awaited by anything that would surface a
            # failure. A done-callback observes it immediately instead.
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                _logger.error("ws task failed", exc_info=exc)

        def _start_live() -> asyncio.Task:
            t = asyncio.create_task(live())
            t.add_done_callback(_log_task_exception)
            return t

        async def live():
            while True:
                await sock.send_json(await q.get())

        async def run_replay(t0: float, t1: float, speed: float):
            # On normal completion (replay_end sent) or an unexpected error
            # (e.g. a DB read failing mid-replay), fall back to live
            # automatically -- an operator who started a replay and then
            # walks away (or hit a transient failure) should not be left
            # staring at a frozen view. Cancellation (an explicit
            # {"cmd":"live"} mid-replay, or a disconnect) must skip the
            # restart below and re-raise instead: the {"cmd":"live"} handler
            # already starts its own live_task synchronously, and restarting
            # here too (e.g. unconditionally in a `finally`) would leave two
            # tasks concurrently racing sock.send_json()/q.get() against each
            # other over the same socket and queue.
            nonlocal live_task
            try:
                async for m in replay_messages(app.epochs, app.events, t0, t1, speed):
                    await sock.send_json(m)
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception("replay failed")
                try:
                    await sock.send_json({"type": "error", "detail": "replay failed"})
                except Exception:
                    _logger.exception("failed to send replay error to client")
            live_task = _start_live()

        live_task: asyncio.Task | None = _start_live()
        try:
            while True:
                cmd = await sock.receive_json()
                if cmd.get("cmd") == "replay":
                    validated = _validate_replay_cmd(cmd)
                    if validated is None:
                        await sock.send_json({"type": "error", "detail": "invalid replay command"})
                        continue
                    t0, t1, speed = validated
                    if live_task is not None:
                        live_task.cancel()
                        live_task = None
                    if replay_task is not None:
                        replay_task.cancel()
                    replay_task = asyncio.create_task(run_replay(t0, t1, speed))
                elif cmd.get("cmd") == "live":
                    if replay_task is not None:
                        replay_task.cancel()
                        replay_task = None
                    if live_task is None or live_task.done():
                        live_task = _start_live()
        except WebSocketDisconnect:
            pass
        finally:
            for t in (live_task, replay_task):
                if t is not None:
                    t.cancel()
            app.broadcaster.unsubscribe(q)

    api.mount("/", StaticFiles(directory=str(_web_dir(app)), html=True), name="web")
    return api
