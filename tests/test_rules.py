from rtk_monitor.config import DiagnosisCfg
from rtk_monitor.diagnosis.rules import DiagnosisInput, Verdict, diagnose
from rtk_monitor.parsers.rtksol import RtkSolution
from rtk_monitor.parsers.rtkstat import SatStat

CFG = DiagnosisCfg()


def _sol(q=1, ns=38, ratio=25.0, age=0.8, sdn=0.011, sde=0.012):
    return RtkSolution(t=1000.0, lat=44.5, lon=90.28, alt=617.0, q=q, ns=ns,
                       sdn=sdn, sde=sde, sdu=0.03, age=age, ratio=ratio)


def _inp(**kw):
    base = dict(now=1000.0, corr_last_t=999.5, corr_age=0.8, base_offset_m=0.0,
                sol=_sol(), sol_t=999.8, sats=[], slip_count_30s=0,
                divergence_m=None, divergence_since=None)
    base.update(kw)
    return DiagnosisInput(**base)


def test_all_good_is_fixed():
    v = diagnose(_inp(), CFG)
    assert v.code == "rtk_fixed" and v.level == "ok"


def test_rule1_corr_outage_wins_over_everything():
    v = diagnose(_inp(corr_last_t=990.0, sol=_sol(q=2, ratio=1.5)), CFG)
    assert v.code == "corr_outage" and v.level == "serious"
    assert "差分中断 10s" in v.message


def test_rule1_age_overrun():
    v = diagnose(_inp(corr_age=15.0), CFG)
    assert v.code == "corr_outage"


def test_rule2_base_shift():
    v = diagnose(_inp(base_offset_m=0.8), CFG)
    assert v.code == "base_shift" and v.level == "critical"
    assert "0.80" in v.message


def test_rule3_low_sats():
    v = diagnose(_inp(sol=_sol(ns=4)), CFG)
    assert v.code == "low_sats" and "4" in v.message


def test_rule4_multipath():
    sats = [SatStat(0, "C08", 90, 15, 3.5, 30, True, 0, 0),
            SatStat(0, "G17", 120, 12, 2.8, 33, True, 0, 0)]
    v = diagnose(_inp(sats=sats, sol=_sol(q=2, ratio=1.5)), CFG)
    assert v.code == "multipath" and "C08" in v.message and "G17" in v.message


def test_rule5_float_low_ratio():
    v = diagnose(_inp(sol=_sol(q=2, ratio=1.8)), CFG)
    assert v.code == "ambiguity" and "1.8" in v.message


def test_rule6_cycle_slips():
    v = diagnose(_inp(slip_count_30s=9), CFG)
    assert v.code == "cycle_slip"


def test_rule7_divergence_needs_hold():
    v = diagnose(_inp(divergence_m=0.5, divergence_since=998.0), CFG)
    assert v.code == "rtk_fixed"          # only 2 s, hold is 5 s
    v = diagnose(_inp(divergence_m=0.5, divergence_since=990.0), CFG)
    assert v.code == "device_divergence" and "0.50" in v.message


def test_no_data_at_all():
    v = diagnose(_inp(sol=None, sol_t=None, corr_last_t=None, corr_age=None), CFG)
    assert v.code == "no_data" and v.level == "warning"
