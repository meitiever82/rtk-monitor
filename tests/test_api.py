# tests/test_api.py — TestClient 覆盖 REST 与 WS 回放（live 推送在 Task 10 端到端验证）
import dataclasses

from fastapi.testclient import TestClient

from rtk_monitor.storage.epochs import Epoch


class _FakeApp:
    """Minimal stand-in exposing exactly what create_api consumes."""
    def __init__(self, tmp_path):
        from rtk_monitor.broadcast import Broadcaster
        from rtk_monitor.config import load_config  # not used; cfg faked below
        from rtk_monitor.diagnosis.base_station import BaseStationMonitor
        from rtk_monitor.storage.epochs import EpochStore
        from rtk_monitor.storage.events import EventStore
        self.epochs = EpochStore(tmp_path / "a.db")
        self.events = EventStore(tmp_path / "a.db")
        self.broadcaster = Broadcaster()
        self.base_monitor = BaseStationMonitor(self.epochs, warmup_s=1.0)
        self.last_status = {"type": "status", "t": 123.0}
        self.tile_store = None


def _client(tmp_path):
    from rtk_monitor.api import create_api
    fake = _FakeApp(tmp_path)
    return TestClient(create_api(fake)), fake


def test_status_events_epochs(tmp_path):
    c, fake = _client(tmp_path)
    fake.epochs.add(Epoch(t=100.0, src="can", q=4, lat=44.5, lon=90.2))
    fake.events.record(100.0, "diagnosis", "open", "x", level="serious", code="corr_outage")
    assert c.get("/api/status").json()["t"] == 123.0
    evs = c.get("/api/events").json()
    assert evs[0]["code"] == "corr_outage"
    eps = c.get("/api/epochs", params={"src": "can", "t0": 0, "t1": 200}).json()
    assert eps[0]["lat"] == 44.5


def test_base_reset_needs_history(tmp_path):
    c, fake = _client(tmp_path)
    assert c.post("/api/base_reset").status_code == 409
    fake.epochs.add_base(100.0, 1.0, 2.0, 3.0)
    r = c.post("/api/base_reset")
    assert r.status_code == 200 and r.json()["xyz"] == [1.0, 2.0, 3.0]


def test_report_json_and_html(tmp_path):
    c, fake = _client(tmp_path)
    fake.epochs.add(Epoch(t=100.0, src="rtkrcv", q=1))
    assert c.get("/api/report", params={"t0": 0, "t1": 200}).json()["fix_ratio"] == 1.0
    html = c.get("/report", params={"t0": 0, "t1": 200}).text
    assert "固定解可用率" in html


def test_tiles_404_without_store(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/tiles/2/1/1.png").status_code == 404


def test_ws_replay_roundtrip(tmp_path):
    c, fake = _client(tmp_path)
    fake.epochs.add(Epoch(t=100.5, src="can", q=4, lat=44.5, lon=90.2, heading=170.0, speed=5.0))
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"cmd": "replay", "t0": 100.0, "t1": 101.0, "speed": 1000.0})
        kinds = []
        while True:
            m = ws.receive_json()
            kinds.append(m["type"])
            if m["type"] == "replay_end":
                break
        assert "position" in kinds and "status" in kinds
