import asyncio

from rtk_monitor.collectors.tcp import TcpCollector


async def _serve_once(port_box: list, payload: bytes, times: int = 2):
    """Server that sends payload then closes, for `times` client connections."""
    remaining = [times]

    async def handler(reader, writer):
        writer.write(payload)
        await writer.drain()
        writer.close()
        remaining[0] -= 1

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port_box.append(server.sockets[0].getsockname()[1])
    return server, remaining


async def test_receives_data_and_reconnects():
    port_box: list[int] = []
    server, remaining = await _serve_once(port_box, b"rtcm-bytes")
    got: list[bytes] = []
    events: list[tuple[str, str]] = []
    c = TcpCollector("corr", "127.0.0.1", port_box[0],
                     on_data=lambda d, t: got.append(d),
                     on_event=lambda n, s, det: events.append((n, s)),
                     initial_backoff=0.01, max_backoff=0.05)
    task = asyncio.create_task(c.run())
    for _ in range(200):
        if remaining[0] <= 0 and len(got) >= 2:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    server.close()
    assert b"rtcm-bytes" in got
    assert ("corr", "connected") in events
    assert ("corr", "disconnected") in events
    assert events.count(("corr", "connected")) >= 2  # reconnected after close


async def test_listen_mode_accepts_peer():
    got: list[bytes] = []
    c = TcpCollector("sol", "127.0.0.1", 0, on_data=lambda d, t: got.append(d),
                     on_event=lambda *a: None, listen=True)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.05)
    assert c.bound_port is not None
    _, writer = await asyncio.open_connection("127.0.0.1", c.bound_port)
    writer.write(b"$GPCHC,...\r\n")
    await writer.drain()
    await asyncio.sleep(0.05)
    writer.close()
    task.cancel()
    assert got == [b"$GPCHC,...\r\n"]
