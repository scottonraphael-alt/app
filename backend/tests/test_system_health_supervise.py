import asyncio

import pytest

import security_harness  # noqa: F401

from services import system_health as sh


def test_supervise_stop_crash_and_cancel():
    asyncio.run(_scenario())


async def _scenario():
    sh.reset_registry()

    async def ok():
        return 5

    async def boom():
        raise ValueError("casse")

    async def forever():
        await asyncio.sleep(60)

    assert await sh.supervise("a", ok()) == 5
    assert sh._registry["a"]["state"] == "stopped"

    with pytest.raises(ValueError):
        await sh.supervise("b", boom())
    assert sh._registry["b"]["state"] == "crashed"
    assert "casse" in sh._registry["b"]["last_error"]

    task = asyncio.create_task(sh.supervise("c", forever(), heartbeat_seconds=0.01))
    await asyncio.sleep(0.05)
    assert sh._registry["c"]["state"] == "running"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sh._registry["c"]["state"] == "stopped"
