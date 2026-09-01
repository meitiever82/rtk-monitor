"""FastAPI service: REST, WebSocket (live + replay), report page, tiles, static UI."""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from rtk_monitor.replay import replay_messages
from rtk_monitor.report import compute_report

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"


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
        return [dataclasses.asdict(e) for e in app.epochs.query(src, t0, t1)[-limit:]]

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
            f"<tr><td>{h['hour']}</td><td>{h['epochs']}</td><td>{pct(h['fix_ratio'])}</td></tr>"
            for h in r["hourly"])
        evs = "".join(f"<tr><td>{e['code']}</td><td>{e['level']}</td>"
                      f"<td>{e['duration_s'] or '-'}</td><td>{e['message']}</td></tr>"
                      for e in r["events"])
        fr = "-" if r["fix_ratio"] is None else f"{r['fix_ratio']:.1%}"
        return f"""<html><meta charset="utf-8"><body style="font-family:sans-serif;max-width:800px;margin:2em auto">
<h1>RTK 定位报告</h1><p>固定解可用率：<b>{fr}</b>　基站最大偏移：{r['base_max_offset_m'] or '-'} m</p>
<h2>分小时统计</h2><table border=1 cellpadding=4><tr><th>小时</th><th>历元数</th><th>固定率</th></tr>{rows}</table>
<h2>事件（{len(r['events'])}）</h2><table border=1 cellpadding=4><tr><th>类型</th><th>级别</th><th>时长(s)</th><th>结论</th></tr>{evs}</table>
</body></html>"""

    @api.get("/tiles/{z}/{x}/{y}.png")
    async def tile(z: int, x: int, y: int):
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

        async def live():
            while True:
                await sock.send_json(await q.get())

        async def run_replay(cmd):
            # On normal completion (replay_end sent), fall back to live
            # automatically -- an operator who started a replay and then
            # walks away should not be left staring at a frozen view.
            # Cancellation (an explicit {"cmd":"live"} mid-replay, or a
            # disconnect) short-circuits this coroutine at its next await
            # point, so the restart below only runs on natural completion.
            nonlocal live_task
            async for m in replay_messages(app.epochs, app.events,
                                           float(cmd["t0"]), float(cmd["t1"]),
                                           float(cmd.get("speed", 1.0))):
                await sock.send_json(m)
            live_task = asyncio.create_task(live())

        live_task: asyncio.Task | None = asyncio.create_task(live())
        try:
            while True:
                cmd = await sock.receive_json()
                if cmd.get("cmd") == "replay":
                    if live_task is not None:
                        live_task.cancel()
                        live_task = None
                    if replay_task is not None:
                        replay_task.cancel()
                    replay_task = asyncio.create_task(run_replay(cmd))
                elif cmd.get("cmd") == "live":
                    if replay_task is not None:
                        replay_task.cancel()
                        replay_task = None
                    if live_task is None or live_task.done():
                        live_task = asyncio.create_task(live())
        except WebSocketDisconnect:
            pass
        finally:
            for t in (live_task, replay_task):
                if t is not None:
                    t.cancel()
            app.broadcaster.unsubscribe(q)

    api.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
    return api
