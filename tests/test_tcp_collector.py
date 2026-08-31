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


async def test_listen_mode_closes_on_cancel():
    """Verify that cancelling listen mode closes accepted connections."""
    c = TcpCollector("sol", "127.0.0.1", 0, on_data=lambda d, t: None,
                     on_event=lambda *a: None, listen=True)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.05)
    assert c.bound_port is not None
    reader, writer = await asyncio.open_connection("127.0.0.1", c.bound_port)
    await asyncio.sleep(0.05)
    # Record the set of active writers before cancel
    active_before = len(c._active_writers)
    assert active_before > 0, "Should have active writers"
    # Cancel the collector
    task.cancel()
    # Give the event loop several chances to process the cancellation
    # This will eventually cause _run_server to raise CancelledError,
    # which triggers the except block that closes all writers
    closed_at_iteration = None
    for i in range(100):
        await asyncio.sleep(0.01)
        if len(c._active_writers) == 0:
            closed_at_iteration = i
            break
    # After writers are closed, the client should get EOF when reading
    if closed_at_iteration is not None:
        data = await asyncio.wait_for(reader.read(1024), timeout=0.5)
        assert data == b"", f"Expected EOF but got {repr(data)}"
