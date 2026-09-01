from rtk_monitor.parsers.rtkstat import SatStat, SlipWindow, parse_sat_line

LINE = "$SAT,2372,113755.4,G12,1,231.5,18.2,2.31,0.012,1,34.5,1,0,120,0,3,1"


def test_parse_sat_line():
    s = parse_sat_line(LINE)
    assert isinstance(s, SatStat)
    assert s.sat == "G12" and abs(s.tow - 113755.4) < 1e-6
    assert abs(s.az - 231.5) < 1e-6 and abs(s.el - 18.2) < 1e-6
    assert abs(s.resp - 2.31) < 1e-6 and abs(s.snr - 34.5) < 1e-6
    assert s.valid is True and s.slipc == 3 and s.rejc == 1


def test_non_sat_lines_return_none():
    assert parse_sat_line("$POS,2372,113755.4,...") is None
    assert parse_sat_line("$SAT,bad") is None


def test_slip_window_counts_increments_only():
    w = SlipWindow(window_s=30.0)
    w.feed(100.0, "G12", 3)      # first sighting: baseline, no increment
    w.feed(101.0, "G12", 5)      # +2
    w.feed(102.0, "C08", 1)      # baseline
    w.feed(103.0, "C08", 2)      # +1
    assert w.count(now=110.0) == 3
    assert w.count(now=140.0) == 0     # both increments aged out (>30 s)
