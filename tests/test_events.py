from rtk_monitor.storage.events import EventStore


def test_record_and_query(tmp_path):
    s = EventStore(tmp_path / "e.db")
    rid = s.record(100.0, "corrections_link", "disconnected", "retry in 1s")
    assert rid >= 1
    s.record(101.0, "corrections_link", "connected")
    rows = s.query()
    assert len(rows) == 2
    assert rows[0].etype == "corrections_link" and rows[0].state == "disconnected"
    assert s.query(since=100.5)[0].state == "connected"
    s.close()


def test_reopen_persists(tmp_path):
    p = tmp_path / "e.db"
    s = EventStore(p)
    s.record(1.0, "x", "open")
    s.close()
    assert len(EventStore(p).query()) == 1
