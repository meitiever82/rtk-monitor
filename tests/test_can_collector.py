import asyncio

import can

from rtk_monitor.collectors.can import CanCollector
from rtk_monitor.storage.canlog import CandumpWriter


async def test_collector_receives_virtual_bus_frames():
    with can.Bus(interface="virtual", channel="t0") as tx, \
         can.Bus(interface="virtual", channel="t0") as rx:
        got: list[tuple[int, bytes]] = []
        c = CanCollector(rx, on_frame=lambda i, d, t: got.append((i, d)))
        task = asyncio.create_task(c.run())
        await asyncio.sleep(0.05)
        tx.send(can.Message(arbitration_id=0x320, data=b"\x01\x02", is_extended_id=False))
        for _ in range(100):
            if got:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        assert got == [(0x320, b"\x01\x02")]


def test_candump_writer_format(tmp_path):
    w = CandumpWriter(tmp_path, "can0", clock=lambda: 1756699200.0)
    w.append(0x320, bytes.fromhex("44093c1cc30600aa"), t=1756699200.123456)
    w.close()
    line = next(next(tmp_path.iterdir()).glob("can0_*.log")).read_text().strip()
    assert line == "(1756699200.123456) can0 320#44093C1CC30600AA"
