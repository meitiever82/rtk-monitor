from pathlib import Path
from rtk_monitor.config import load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.yaml.example"

def test_load_example_config():
    cfg = load_config(EXAMPLE)
    assert cfg.data_root == Path("/data/gnsslog")
    assert cfg.corrections.host == "192.168.10.1"
    assert cfg.corrections.port == 6001
    assert cfg.corrections.listen is False          # default
    assert cfg.gnss_solution.listen is True
    assert cfg.can_channel == "can0"
    assert cfg.reserve_corrections_port == 15010
    assert cfg.reserve_raw_obs_port == 15011
    assert cfg.retention_days == 14
    assert cfg.disk_watermark_pct == 85.0

def test_missing_key_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("data_root: /tmp/x\n")
    try:
        load_config(p)
        assert False, "should raise"
    except KeyError:
        pass
