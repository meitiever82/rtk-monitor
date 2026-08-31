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
