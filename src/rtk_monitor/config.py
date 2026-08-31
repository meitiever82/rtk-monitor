"""Load and validate config.yaml into typed dataclasses."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class StreamCfg:
    host: str
    port: int
    listen: bool = False


@dataclass(frozen=True)
class Config:
    data_root: Path
    db_path: Path
    corrections: StreamCfg
    raw_obs: StreamCfg
    gnss_solution: StreamCfg
    can_channel: str
    reserve_corrections_port: int
    reserve_raw_obs_port: int
    retention_days: int
    disk_watermark_pct: float


def _stream(d: dict) -> StreamCfg:
    return StreamCfg(host=d["host"], port=int(d["port"]), listen=bool(d.get("listen", False)))


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    return Config(
        data_root=Path(raw["data_root"]),
        db_path=Path(raw["db_path"]),
        corrections=_stream(raw["corrections"]),
        raw_obs=_stream(raw["raw_obs"]),
        gnss_solution=_stream(raw["gnss_solution"]),
        can_channel=raw["can_channel"],
        reserve_corrections_port=int(raw["reserve"]["corrections_port"]),
        reserve_raw_obs_port=int(raw["reserve"]["raw_obs_port"]),
        retention_days=int(raw["retention_days"]),
        disk_watermark_pct=float(raw["disk_watermark_pct"]),
    )
