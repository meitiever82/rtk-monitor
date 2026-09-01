"""Tests for report statistics."""
from rtk_monitor.report import compute_report
from rtk_monitor.storage.epochs import Epoch, EpochStore
from rtk_monitor.storage.events import EventStore


def test_report_stats(tmp_path):
    ep = EpochStore(tmp_path / "r.db"); ev = EventStore(tmp_path / "r.db")
    base = 3600.0 * 100
    for i in range(10):
        ep.add(Epoch(t=base + i, src="rtkrcv", q=1 if i < 8 else 2))
    ep.add(Epoch(t=base + 3700, src="rtkrcv", q=1))
    rid = ev.record(base + 2, "diagnosis", "open", "差分中断", level="serious", code="corr_outage")
    ev.close_event(rid, base + 30)
    ep.add_base(base, -2148744.0, 4426641.0, 4044655.0)
    ep.add_base(base + 50, -2148744.5, 4426641.0, 4044655.0)

    r = compute_report(ep, ev, base, base + 7200)
    assert abs(r["fix_ratio"] - 9 / 11) < 1e-9
    assert r["hourly"][0]["epochs"] == 10 and abs(r["hourly"][0]["fix_ratio"] - 0.8) < 1e-9
    assert r["events"][0]["code"] == "corr_outage" and r["events"][0]["duration_s"] == 28.0
    assert abs(r["base_max_offset_m"] - 0.5) < 1e-6
    assert r["epoch_counts"]["rtkrcv"] == 11


def test_report_empty_range(tmp_path):
    ep = EpochStore(tmp_path / "r.db"); ev = EventStore(tmp_path / "r.db")
    r = compute_report(ep, ev, 0.0, 100.0)
    assert r["fix_ratio"] is None and r["events"] == [] and r["base_max_offset_m"] is None
