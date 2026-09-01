"""Generate rtkrcv.conf and supervise the rtkrcv subprocess.

Config keys target RTKLIB demo5; verifying exact key names against the real
binary is an integration step (docs/integration-rtkrcv.md), not a unit test.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Callable

_logger = logging.getLogger(__name__)


def _signal_group(proc, sig):
    """Signal a process group to ensure child and grandchild termination."""
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass

_CONF_TEMPLATE = """\
inpstr1-type =tcpcli
inpstr1-path =127.0.0.1:{obs_port}
inpstr1-format =rtcm3
inpstr2-type =tcpcli
inpstr2-path =127.0.0.1:{corr_port}
inpstr2-format =rtcm3
outstr1-type =tcpsvr
outstr1-path =:{sol_port}
outstr1-format =llh
pos1-posmode =kinematic
pos1-navsys =63
pos1-elmask =10
pos2-armode =continuous
out-solformat =llh
out-outhead =off
out-timesys =gpst
misc-svrcycle =10
"""


class RtkrcvManager:
    def __init__(self, binary: str, run_dir: Path, corr_port: int, obs_port: int,
                 sol_port: int, extra_args: tuple[str, ...] = (),
                 restart_delay: float = 5.0,
                 on_event: Callable[[str, str, str], None] | None = None) -> None:
        self._binary = binary
        self._run_dir = Path(run_dir)
        self._corr_port = corr_port
        self._obs_port = obs_port
        self._sol_port = sol_port
        self._extra = extra_args
        self._delay = restart_delay
        self._on_event = on_event

    def write_conf(self) -> Path:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        conf = self._run_dir / "rtkrcv.conf"
        conf.write_text(_CONF_TEMPLATE.format(
            obs_port=self._obs_port, corr_port=self._corr_port,
            sol_port=self._sol_port))
        return conf

    async def run(self) -> None:
        conf = self.write_conf()
        env = dict(os.environ, RTKRCV_SOL_PORT=str(self._sol_port))
        while True:
            proc = None
            try:
                # extra_args precede the fixed flags: lets tests spawn
                # "python fake_rtkrcv.py ..." (Task 13); empty for the real binary
                proc = await asyncio.create_subprocess_exec(
                    self._binary, *self._extra, "-s", "-nc", "-o", str(conf),
                    cwd=self._run_dir, env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True)
                if self._on_event:
                    self._on_event("rtkrcv", "connected", f"pid {proc.pid}")
                rc = await proc.wait()
                if self._on_event:
                    self._on_event("rtkrcv", "disconnected", f"exit code {rc}")
            except asyncio.CancelledError:
                if proc is not None and proc.returncode is None:
                    _signal_group(proc, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), 5.0)
                    except asyncio.TimeoutError:
                        _signal_group(proc, signal.SIGKILL)
                        await proc.wait()
                raise
            except Exception:
                _logger.exception("rtkrcv spawn failed")
                if self._on_event:
                    self._on_event("rtkrcv", "disconnected", "spawn failed")
            await asyncio.sleep(self._delay)
