import asyncio
import json
import socket
import struct
import textwrap

from rtk_monitor.config import load_config
from rtk_monitor.main import build_app
from rtk_monitor.parsers.rtcm import crc24q


def _cfg(tmp_path, udp_port, corr_port):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(f"""\
        data_root: {tmp_path}/log
        db_path: {tmp_path}/rtk.db
        corrections: {{host: 127.0.0.1, port: {corr_port}}}
        raw_obs: {{host: 127.0.0.1, port: 1, listen: false}}
        gnss_solution: {{host: 127.0.0.1, port: 0, listen: true}}
        can_channel: virtual:p2app
        reserve: {{corrections_port: 0, raw_obs_port: 0}}
        retention_days: 14
        disk_watermark_pct: 85.0
        publish: {{enabled: true, host: 127.0.0.1, port: {udp_port}}}
        diagnosis: {{corr_gap_s: 0.5, close_hysteresis_s: 0.5}}
        """))
    return load_config(p)


def _gpchc_line():
    body = ("GPCHC,2372,113755.36,174.20,1.25,-0.80,0.12,-0.05,0.30,"
            "0.0123,-0.0045,0.9987,44.50123456,90.28765432,617.123,"
            "0.02,-0.01,0.00,0.02,39,38,42,1.2,0")
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"${body}*{cs:02X}\r\n".encode()


async def test_epochs_and_corr_outage_event(tmp_path):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0)); rx.setblocking(False)
    # corrections server: sends one 1074 frame then goes silent -> outage
    payload = (1074 << 4).to_bytes(2, "big") + b"\x00" * 6
    head = bytes([0xD3, 0x00, len(payload)])
    frame = head + payload + crc24q(head + payload).to_bytes(3, "big")

    async def corr_handler(reader, writer):
        writer.write(frame)
        await writer.drain()
        await asyncio.sleep(30)
    corr_srv = await asyncio.start_server(corr_handler, "127.0.0.1", 0)
    corr_port = corr_srv.sockets[0].getsockname()[1]

    app = build_app(_cfg(tmp_path, rx.getsockname()[1], corr_port))
    task = asyncio.create_task(app.run_forever())
    await asyncio.sleep(0.1)
    # feed route 3 (GPCHC) via listen port
    _, w = await asyncio.open_connection("127.0.0.1", app.sol_collector_port())
    w.write(_gpchc_line()); await w.drain()
    await asyncio.sleep(2.5)          # > corr_gap_s: outage rule must fire
    task.cancel()
    await app.shutdown()

    assert app.epochs.latest("gpchc").sats == 39
    codes = [e.code for e in app.events.query() if e.etype == "diagnosis"]
    assert "corr_outage" in codes
    # event also published on UDP
    loop = asyncio.get_running_loop()
    seen = []
    try:
        while True:
            data = await asyncio.wait_for(loop.sock_recv(rx, 4096), 0.3)
            seen.append(json.loads(data.decode()))
    except asyncio.TimeoutError:
        pass
    assert any(m["type"] == "gnss_event" and m["event"] == "corr_outage" for m in seen)
    w.close(); corr_srv.close(); rx.close()
