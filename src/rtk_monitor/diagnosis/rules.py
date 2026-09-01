"""Pure diagnosis rule chain (spec §4.2): first matching rule wins."""
from __future__ import annotations

from dataclasses import dataclass, field

from rtk_monitor.config import DiagnosisCfg
from rtk_monitor.parsers.rtksol import RtkSolution
from rtk_monitor.parsers.rtkstat import SatStat


@dataclass(frozen=True)
class DiagnosisInput:
    now: float
    corr_last_t: float | None          # host time of last RTCM message
    corr_age: float | None             # differential age from solution (s)
    base_offset_m: float | None        # 1005 offset vs learned baseline
    sol: RtkSolution | None            # latest independent solution
    sol_t: float | None                # host time it arrived
    sats: list[SatStat] = field(default_factory=list)
    slip_count_30s: int = 0
    divergence_m: float | None = None      # |610 fused - rtkrcv| horizontal
    divergence_since: float | None = None  # host time divergence first exceeded
    solver_enabled: bool = True


@dataclass(frozen=True)
class Verdict:
    level: str    # ok | info | warning | serious | critical
    code: str
    message: str


def diagnose(inp: DiagnosisInput, cfg: DiagnosisCfg) -> Verdict:
    if inp.sol is None and inp.corr_last_t is None:
        return Verdict("warning", "no_data", "无数据——检查采集链路与设备连接")

    # Rule 1: correction outage / age overrun
    gap = inp.now - inp.corr_last_t if inp.corr_last_t is not None else None
    if (gap is not None and gap > cfg.corr_gap_s) or \
       (inp.corr_age is not None and inp.corr_age > cfg.age_max_s):
        n = int(gap if gap is not None and gap > cfg.corr_gap_s else inp.corr_age)
        return Verdict("serious", "corr_outage",
                       f"差分中断 {n}s——5G 链路或平台转发问题")

    # Rule 2: base station coordinate shift
    if inp.base_offset_m is not None and inp.base_offset_m > cfg.base_shift_m:
        return Verdict("critical", "base_shift",
                       f"⚠ 基站坐标变动 {inp.base_offset_m:.2f}m——全矿定位将整体平移")

    # Rule 3: too few satellites
    if inp.sol is not None and inp.sol.ns < cfg.min_sats:
        return Verdict("serious", "low_sats",
                       f"卫星数不足（{inp.sol.ns} 颗）——高帮/坑底遮挡")

    # Rule 4: multipath suspects
    bad = [s for s in inp.sats
           if s.resp > cfg.resid_max_m and (s.el < cfg.low_el_deg or s.snr < cfg.low_snr_dbhz)]
    if len(bad) >= 2:
        names = "、".join(s.sat for s in bad[:4])
        return Verdict("warning", "multipath", f"{names} 残差异常——疑似多路径")

    # Rule 5: ambiguity not fixed
    if inp.sol is not None and inp.sol.q == 2 and inp.sol.ratio < cfg.min_ratio:
        return Verdict("warning", "ambiguity",
                       f"模糊度无法固定（ratio={inp.sol.ratio:.1f}）——遮挡过渡区常见")

    # Rule 6: frequent cycle slips
    if inp.slip_count_30s > cfg.slip_max_per_30s:
        return Verdict("warning", "cycle_slip",
                       "载波频繁失锁——动态遮挡或天线/馈线问题")

    # Rule 7: 610 output diverges from independent solution
    if (inp.divergence_m is not None and inp.divergence_since is not None
            and inp.sol is not None
            and inp.divergence_m > cfg.divergence_sigma * max(
                1e-3, (inp.sol.sdn ** 2 + inp.sol.sde ** 2) ** 0.5)
            and inp.now - inp.divergence_since >= cfg.divergence_hold_s):
        return Verdict("serious", "device_divergence",
                       f"610 输出与独立解算偏差 {inp.divergence_m:.2f}m——疑似 610 融合问题")

    # Check for missing solver output
    if inp.sol is None:
        if inp.solver_enabled:
            return Verdict("warning", "no_solution",
                           "独立解算无输出——rtkrcv 未运行或未收敛")
        return Verdict("info", "no_solution", "独立解算未启用")

    if inp.sol.q != 1:
        return Verdict("info", "not_fixed", f"非固定解（Q={inp.sol.q}）")
    return Verdict("ok", "rtk_fixed", "RTK 固定")
