import asyncio
import os
import stat

from rtk_monitor.solver.rtkrcv import RtkrcvManager


def _fake_binary(tmp_path, body: str) -> str:
    p = tmp_path / "fake_rtkrcv"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_write_conf(tmp_path):
    m = RtkrcvManager("/bin/true", tmp_path, corr_port=15010, obs_port=15011,
                      sol_port=15020)
    conf = m.write_conf()
    text = conf.read_text()
    assert "inpstr1-path =127.0.0.1:15011" in text      # rover = raw obs
    assert "inpstr2-path =127.0.0.1:15010" in text      # base = corrections
    assert "outstr1-path =:15020" in text
    assert "pos1-posmode =kinematic" in text


async def test_restarts_after_exit_and_terminates_on_cancel(tmp_path):
    marker = tmp_path / "runs"
    binary = _fake_binary(
        tmp_path, f'echo run >> "{marker}"\nsleep 0.1\n')
    events = []
    m = RtkrcvManager(binary, tmp_path, 15010, 15011, 15020,
                      restart_delay=0.05,
                      on_event=lambda n, s, d: events.append((n, s)))
    task = asyncio.create_task(m.run())
    await asyncio.sleep(0.6)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert marker.read_text().count("run") >= 2          # restarted at least once
    assert ("rtkrcv", "disconnected") in events


async def test_sol_port_in_env(tmp_path):
    out = tmp_path / "env"
    binary = _fake_binary(tmp_path, f'echo "$RTKRCV_SOL_PORT" > "{out}"\nsleep 5\n')
    m = RtkrcvManager(binary, tmp_path, 15010, 15011, 15021, restart_delay=9)
    task = asyncio.create_task(m.run())
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert out.read_text().strip() == "15021"
