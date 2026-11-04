import asyncio
import pytest
from services.workflow_batch import process


def test_slow_or_failed_dossier_does_not_block_others_and_concurrency_is_bounded():
    async def run():
        gate, progressed = asyncio.Event(), asyncio.Event()
        active = peak = 0
        seen = []
        async def rows():
            for ident in range(20):
                yield {'_id': ident}
        async def handle(row):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                if row['_id'] == 0:
                    await gate.wait()
                elif row['_id'] == 1:
                    raise RuntimeError('one dossier failed')
                else:
                    seen.append(row['_id'])
                    progressed.set()
                    await asyncio.sleep(0)
            finally:
                active -= 1
        task = asyncio.create_task(process(rows(), handle, limit=3))
        try:
            await asyncio.wait_for(progressed.wait(), 1)
            assert not gate.is_set()  # completed without waiting for the slow dossier
            gate.set()
            await asyncio.wait_for(task, 1)
            assert peak <= 3 and len(seen) == 18
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_cancellation_stops_all_child_workers():
    async def run():
        started = asyncio.Event()
        active = 0
        async def rows():
            for ident in range(100):
                yield {'_id': ident}
        async def handle(row):
            nonlocal active
            active += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
        task = asyncio.create_task(process(rows(), handle))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert active == 0
    asyncio.run(run())
