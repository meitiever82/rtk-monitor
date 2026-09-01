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
class RtkrcvCfg:
    binary: str = ""
    sol_port: int = 15020
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosisCfg:
    corr_gap_s: float = 3.0
    age_max_s: float = 10.0
    base_shift_m: float = 0.1
    min_sats: int = 6
    resid_max_m: float = 2.0
    low_el_deg: float = 20.0
    low_snr_dbhz: float = 35.0
    min_ratio: float = 3.0
    slip_max_per_30s: int = 5
    divergence_sigma: float = 3.0
    divergence_hold_s: float = 5.0
    close_hysteresis_s: float = 10.0


@dataclass(frozen=True)
class PublishCfg:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 15030


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
    rtkrcv: RtkrcvCfg
    diagnosis: DiagnosisCfg
    publish: PublishCfg


def _stream(d: dict) -> StreamCfg:
    return StreamCfg(host=d["host"], port=int(d["port"]), listen=bool(d.get("listen", False)))


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    r = raw.get("rtkrcv") or {}
    d = raw.get("diagnosis") or {}
    p = raw.get("publish") or {}
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
        rtkrcv=RtkrcvCfg(binary=str(r.get("binary", "")),
                         sol_port=int(r.get("sol_port", 15020)),
                         extra_args=tuple(r.get("extra_args", []))),
        diagnosis=DiagnosisCfg(**{k: type(getattr(DiagnosisCfg, k))(v)
                                  for k, v in d.items()}),
        publish=PublishCfg(enabled=bool(p.get("enabled", False)),
                           host=str(p.get("host", "127.0.0.1")),
                           port=int(p.get("port", 15030))),
    )
