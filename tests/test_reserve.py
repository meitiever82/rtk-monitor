import asyncio

from rtk_monitor.collectors.reserve import LocalReserver


async def test_broadcast_to_multiple_clients():
    r = LocalReserver()
    await r.start(0)
    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", r.bound_port)
        data = await reader.readexactly(5)
        writer.close()
        return data
    t1, t2 = asyncio.create_task(client()), asyncio.create_task(client())
    await asyncio.sleep(0.05)
    r.broadcast(b"hello")
    assert await t1 == b"hello" and await t2 == b"hello"
    await r.stop()


async def test_broadcast_with_no_clients_is_noop():
    r = LocalReserver()
    await r.start(0)
    r.broadcast(b"x")  # must not raise
    await r.stop()


async def test_broadcast_force_closes_stalled_clients():
    r = LocalReserver()
    await r.start(0)

    async def stalled_client():
        reader, writer = await asyncio.open_connection("127.0.0.1", r.bound_port)
        # Don't read — simulate a stalled client
        await asyncio.sleep(10)

    task = asyncio.create_task(stalled_client())
    await asyncio.sleep(0.05)  # Let client connect

    # Monkeypatch the transport's get_write_buffer_size to simulate a full buffer
    writer = list(r._writers)[0]
    writer.transport.get_write_buffer_size = lambda: 10 * 1024 * 1024

    # Broadcast should force-close the stalled client
    r.broadcast(b"x")

    # Assert the writer was removed and is closing
    assert writer not in r._writers
    assert writer.is_closing()

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await r.stop()
